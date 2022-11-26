#!/usr/bin/env python3

import time
import sys
import getopt
import os
import sys
from app import app
from config import samples_path
import soundfile as sf
import numpy as np


test_event = '_test'


def apiRec(json: dict):
    response = app.test_client().put('/api/rec', json=json)
    assert response.status_code == 200


def test_ffmpeg_input():
    apiRec({'action':'device', 'index': '1'})
    apiRec({'action':'start'})
    time.sleep(2.5)
    apiRec({'action':'save', 'event':test_event, 'fold':'1'})
    print("OK")


def test_ffmpeg_output():
    data,sample_rate = sf.read((samples_path / test_event).with_suffix('.wav'))
    assert sample_rate == app.config.get('SAMPLE_RATE')
    duration = app.config.get('REC_DURATION')
    y = np.fft.rfft(data)
    x = np.fft.rfftfreq(sample_rate*duration, 1/sample_rate)
    assert x[np.argmax(np.abs(y))] == 440
    print("OK")


def main():
    fmt = os.environ.get('FLASK_INPUT_FORMAT')
    if fmt != 'lavfi':
        print("environment variable 'FLASK_INPUT_FORMAT' should be "
              "set to 'lavfi' for this test")
        sys.exit(1)
    try:
        opts,args = getopt.getopt(sys.argv[1:], 'io')
    except getopt.GetoptError as e:
        print(e)
        raise
    for o,a in opts:
        if o == '-i':
            test_ffmpeg_input()
        if o == '-o':
            test_ffmpeg_output()


if __name__ == '__main__':
    main()
