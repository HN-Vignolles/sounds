#!/usr/bin/env python3

import time,sys,getopt
from app import app
from config import samples_path
import matplotlib.pyplot as plt
import soundfile as sf
import numpy as np

test_wav = '_test2'

def apiRec(json:dict):
    response = app.test_client().put('/api/rec',json=json)
    assert response.status_code == 200

def test_ffmpeg_input():
    apiRec({'action':'device','index':'1'})
    apiRec({'action':'start'})
    time.sleep(2.5)
    apiRec({'action':'save','event':'_test2','fold':'1'})

def test_ffmpeg_output():
    data,sample_rate =  sf.read(samples_path / '_test2.wav')
    assert sample_rate == app.config.get('SAMPLE_RATE')
    duration = app.config.get('REC_DURATION')
    y = np.fft.rfft(data)
    x = np.fft.rfftfreq(sample_rate*duration,1/sample_rate)
    print(x[np.argmax(np.abs(y))])
    
def main():
    try:
        opts,args = getopt.getopt(sys.argv[1:],'io')
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