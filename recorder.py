import code
import os
import uuid
from threading import Timer

import numpy as np
import pandas as pd
import sounddevice as sd
import soundfile as sf


df_columns = ['filename','target','category','fold']
pd.set_option('max_colwidth',None)


class RecorderBase():
    def __init__(self,sample_duration,fs):
        self._sample_duration = sample_duration
        self._fs = fs
        self._last = ''
        self._recording = False
        self._elapsed = 0.0
        self._timer = None
        self._buffLen = 60

    def _start_timer(self):
        self._timer = Timer(0.1,self._start_timer)
        self._timer.start()
        self._elapsed += 0.1
        if round(self._elapsed,2) % 1 == 0:
            ...
            #print('{:.04f}'.format(self._elapsed),end='\n',flush=True)

    def start(self):
        """start recording"""

    def cancel(self):
        """stop recording without saving (backend)"""

    def query_devices(self):
        """query source devices"""

    def setDevice(self,device):
        """set input device"""
    
    def is_recording(self):
        return self._recording()

    @property
    def elapsed(self):
        return self._elapsed

# name == 'posix':
class Recorder(RecorderBase):
    def __init__(self,samples_path,input_device,
                 sample_duration=2,fs=44100):
        super().__init__(sample_duration,fs)
        if not input_device:
            raise ValueError("input_device must be supplied")
        if not samples_path:
            raise ValueError("samples_path must be supplied")
        sd.default.device = input_device
        self._samples_path = samples_path
        self._df_csv = os.path.join(samples_path,'samples.csv')
        if not os.path.exists(self._df_csv):
            df = pd.DataFrame(columns=df_columns)
            df.to_csv(self._df_csv,index=False)

    def start(self):
        if not self._recording:
            self._recording = True
            self._sample = sd.rec(int(self._buffLen*self._fs),samplerate=self._fs,channels=1)
            self._start_timer()

    def cancel(self):
        if self._timer and self._timer.is_alive():
            self._timer.cancel()
            self._recording = False
            self._elapsed = 0.0
            sd.stop()

    def query_devices(self):
        return sd.query_devices()

    def setDevice(self,device):
        sd.default.device = device

    def save(self,name,fold):
        if self._timer and self._recording:
            len = 0
            self._timer.cancel()
            sd.stop()
            self._recording = False
            if any(self._sample):
                filename = os.path.join(self._samples_path,f'{name}-{uuid.uuid4()}.wav')
                start = int(self._fs * (self._elapsed-self._sample_duration))
                end = int(self._fs * self._elapsed)
                self._sample[np.isnan(self._sample)] = 0
                self._sample[self._sample > 1] = 0
                self._sample[self._sample < -1] = 0

                # check minimum sample length:
                if start > 0:
                    sf.write(filename,self._sample[start:end],samplerate=self._fs,subtype='PCM_16')
                    df = pd.read_csv(self._df_csv)
                    s = pd.Series([filename,-1,name,fold],index=df_columns)
                    df = pd.concat([df, s.to_frame().T])
                    df.to_csv(self._df_csv,index=False)
                    self._last = filename
                    len = end - start
                
                #print(f'sample: {self._sample[start:end].flatten()}')
            
            self._elapsed = 0
            x = np.linspace(0,self._sample_duration,len)
            return x.tolist(),self._sample[start:end].flatten().tolist()

if __name__ == "__main__":
    rec = Recorder()
    code.interact(local=dict(globals(),**locals()))