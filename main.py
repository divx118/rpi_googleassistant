#!/usr/bin/env python3
# Copyright 2017 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Run a recognizer using the Google Assistant Library.

The Google Assistant Library has direct access to the audio API, so this Python
code doesn't need to record audio. Hot word detection "OK, Google" is supported.

It is available for Raspberry Pi 2/3 only; Pi Zero is not supported.
"""

import logging
import platform
import subprocess
import sys
import threading

from google.assistant.library.event import EventType

from aiy.assistant import auth_helpers
from aiy.assistant.library import Assistant
from aiy.board import Board, Led
from aiy.voice import tts

# Define id snapcast clients
kitchen = "9255b82e-84fb-7459-e7af-a0910638aaab"
living_room = "3a932931-8d26-b4ae-37db-7139f4e1874c"
mpd_server = "192.168.178.4"
mpd_port = "6600"
mpd_commands = "search pause play stop clear next previous song shuffle"
mpd_trigger = "music"

# Clean shell output
def cln(ret):
    return ret.strip().decode('utf-8')

# some functions to control snapcast, maybe rewrite this by removing the shell calls
def set_mute_snap(mute,id):
    subprocess.call("echo \'{\"id\":5,\"jsonrpc\":\"2.0\",\"method\": \
        \"Group.SetMute\",\"params\":{\"id\":\""+ id + "\", \
        \"mute\":" + mute + "}} \' | nc -w 1 192.168.178.4 1705", shell=True)
    
def get_muted_snap(id):
    muted = cln(subprocess.check_output("echo \'{\"id\":5,\"jsonrpc\":\"2.0\",\"method\": \
        \"Group.GetStatus\",\"params\":{\"id\":\"" + id + "\"}} \' | nc -w 1 192.168.178.4 1705 | \
        grep -o -P \'(?<=,\"muted\":).*?(?=,)\'", shell=True))
    return muted

def get_volume_snap(id):
    output = cln(subprocess.check_output("echo \'{\"id\":5,\"jsonrpc\":\"2.0\",\"method\": \
        \"Group.GetStatus\",\"params\":{\"id\":\"" + id + "\"}} \' | nc -w 1 192.168.178.4 1705 | \
        grep -o -P \'(?<=\"volume\":{).*?(?=})\'", shell=True))
    muted, volume = output.split(',')
    muted = muted.split(':')[1]
    volume = volume.split(':')[1]
    print(muted)
    print(volume)
    return {'muted':muted, 'volume':volume}

# Handle mpc commands to control mpd
def music_pi(music,self):
    print (music)
    if 'search' in music:
        search = music.split('search')[-1][1:]
        if search == "":
            return
        # Make Artist default search type
        if  search.split()[0] not in "album title genre":
            type = "artist"
        else:
            type = search.split()[0]
            search = ' '.join(search.split()[1:])
            print (search)
        result = cln(subprocess.check_output('mpc search ' + type + ' \"' + \
            search + '\"', shell = True))
        if search == "" or result == "":
            aiy.audio.say('Sorry, no results for ' + search)
            return
        else:
            com = 'searchadd ' + type +' \"' + search + '\"'
            subprocess.call("mpc clear", shell = True)
    elif 'pause' in music or 'stop' in music:
        com = 'pause'
        self._mpc_is_playing = False
    elif 'play' == music.split()[-1]:
        com = 'play'
        self._can_restart_conversation = False
    elif 'clear' in music:
        com = 'clear'
    elif 'play' in music:
        com = 'searchplay \"' + music.split('play')[-1][1:] + '\"'
    elif 'next' in music:
        com = 'next'
    elif 'previous' in music:
        com = 'prev'
    elif 'song' in music:
        result = cln(subprocess.check_output("mpc | grep -o '#[0-9]*/[0-99]*'" \
            , shell = True))
        if result == "":
            aiy.audio.say('Nothing is playing now')
            return
        else:
            song = cln(subprocess.check_output('mpc current', shell = True))
            aiy.audio.say('Now playing ' + song + ' ' + result.split('/')[0] + \
                ' of ' + result.split('/')[1])
            return
    elif 'shuffle' in music:
        result = cln(subprocess.check_output("mpc random| grep -o \
            'random: [on|off]*'", shell = True))
        print(result.split()[1])
        device = led.matrix(cascaded = 8)
        device.show_message("Hello world!")
        aiy.audio.say('Shuffle is turned ' + result.split()[1])
        return
    else:
         aiy.audio.say('Sorry, I cannot understand what you are saying')
         return
    print(com)
    subprocess.call("mpc -h " + mpd_server + " -p " + mpd_port + " " + com,
                    shell=True)
    
# Assistant class
class MyAssistant:
    """An assistant that runs in the background.

    The Google Assistant Library event loop blocks the running thread entirely.
    To support the button trigger, we need to run the event loop in a separate
    thread. Otherwise, the on_button_pressed() method will never get a chance to
    be invoked.
    """

    def __init__(self):
        self._task = threading.Thread(target=self._run_task)
        self._can_start_conversation = False
        self._is_snap_muted = False
        self._assistant = None
        self._board = Board()
        self._board.button.when_pressed = self._on_button_pressed

    def start(self):
        """Starts the assistant.

        Starts the assistant event loop and begin processing events.
        """
        self._task.start()

    def _run_task(self):
        credentials = auth_helpers.get_assistant_credentials()
        with Assistant(credentials) as assistant:
            self._assistant = assistant
            for event in assistant.start():
                self._process_event(event)
                
    def _process_event(self, event):
        logging.info(event)
        if event.type == EventType.ON_START_FINISHED:
            self._board.led.state = Led.BEACON_DARK  # Ready.
            self._can_start_conversation = True
            print('Say "OK, Google" then speak, or press Ctrl+C to quit...')
        elif event.type == EventType.ON_CONVERSATION_TURN_STARTED:
            self._board.led.state = Led.ON  # Listening.
            self._can_start_conversation = False
            muted = get_muted_snap(living_room)
            print(muted)
            if (muted == "false" and not self._is_snap_muted):
                set_mute_snap('true', living_room)
                self._is_snap_muted = True
        elif (event.type == EventType.ON_RECOGNIZING_SPEECH_FINISHED
              and event.args):
            text = event.args['text'].lower()
            print('You said ###:', event.args['text'])
            print(mpd_commands)
            if text == "":
                self._assistant.send_text_query("repeat after me, you said nothing")
                
            if text is not "":
                print("why are we here")
                
                # Prevent needing to repeat the trigger word 'music' when mpd
                # is playing
                if (self._is_snap_muted and text.split()[0] in mpd_commands):
                    text = mpd_trigger + ' ' + text
                    print('You said:', text)

                if ('set volume' in text or text.split()[0] == 'volume'):
                    self._assistant.stop_conversation()
                    #change_volume_pi(text)
                    print('hello')
                elif (text.split()[0] == mpd_trigger and len(text.split()) > 1):
                    print('mpd command')
                    if text.split()[1] in mpd_commands:
                        self._assistant.stop_conversation()
                        music_pi(text, self)
                elif (text.split()[0] in "enable disable" and len(text.split()) > 1):
                    
                    if text.split()[0] == "enable":
                        mute = 'false'
                    else:
                        mute = 'true'
                    print("@@@@@@@@@@@@@@ " + text.split(" ",1)[1])
                    if text.split(" ",1)[1] == "living room":
                        set_mute_snap(mute, living_room)
                        self._is_snap_muted = False
                        self._assistant.stop_conversation()
                    elif text.split(" ",1)[1] == "kitchen":
                        set_mute_snap(mute, kitchen)
                        self._assistant.stop_conversation()
                    else:
                        self._assistant.send_text_query("repeat after me, I cannot "
                            + text)
                    
            print('No special commands so get assistant response')
        elif event.type == EventType.ON_END_OF_UTTERANCE:
            self._can_start_conversation = False
            self._board.led.state = Led.PULSE_QUICK  # Thinking.
        elif (event.type == EventType.ON_CONVERSATION_TURN_FINISHED
            or event.type == EventType.ON_CONVERSATION_TURN_TIMEOUT
            or event.type == EventType.ON_NO_RESPONSE):
            self._board.led.state = Led.BEACON_DARK  # Ready.
            self._can_start_conversation = True
            print("ok we are here")
            if (self._is_snap_muted
                and event.type == EventType.ON_CONVERSATION_TURN_FINISHED
                and not event.args['with_follow_on_turn']):
                print("ok we are here now")
                set_mute_snap('false', living_room)
                self._is_snap_muted = False
        elif (event.type == EventType.ON_ASSISTANT_ERROR and event.args
              and event.args['is_fatal']):
            sys.exit(1)
            
    def _on_button_pressed(self):
        # Check if we can start a conversation. 'self._can_start_conversation'
        # is False when either:
        # 1. The assistant library is not yet ready; OR
        # 2. The assistant library is already in a conversation.
        if self._can_start_conversation:
            self._assistant.start_conversation()

def main():
    logging.basicConfig(level=logging.INFO)
    MyAssistant().start()


if __name__ == '__main__':
    main()
