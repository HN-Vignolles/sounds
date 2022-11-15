import code
import os
import subprocess
import uuid
from collections import deque
from pathlib import Path
from threading import Lock, Thread, Timer

import numpy as np
import pandas as pd
import sounddevice as sd
import soundfile as sf


df_columns = ['filename','target','category','fold']
pd.set_option('max_colwidth',None)


class RecorderBase():
    def __init__(self,sample_duration,sample_rate):
        self._sample_duration = sample_duration
        self._sample_rate = sample_rate
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
    
    def _start_reader(self):
        self._reader_thread = Thread(target=self._reader,args=())
        self._reader_thread.daemon = True
        self._reader_thread.start()

    def start(self):
        """start recording"""

    def cancel(self):
        """stop recording without saving (backend)"""

    def _reader(self):
        """reader thread to read from the
        ffmpeg stdout into a deque"""

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
import pulsectl

# TODO: set volume (pulsectl)

class Recorder(RecorderBase):
    def __init__(self,samples_path,input_device,
                 sample_duration=2,sample_rate=44100):
        super().__init__(sample_duration,sample_rate)

        if not input_device:
            raise ValueError("input_device must be supplied")
        if not samples_path:
            raise ValueError("samples_path must be supplied")
        
        # https://trac.ffmpeg.org/wiki/Null
        self._input_dev_str = f'-f pulse -i {input_device}'
        self._circ_buff = deque(maxlen=sample_duration * sample_rate * 2)
        self.ffmpeg_cmd = f"/usr/bin/ffmpeg {self._input_dev_str} -ar {sample_rate} -ac 1 -f s16le -".split()
        self._lock = Lock()
        self.samples_path = Path(samples_path)
        self.df_csv = self.samples_path / 'samples.csv'
        if not self.df_csv.exists():
            df = pd.DataFrame(columns=df_columns)
            df.to_csv(self.df_csv,index=False)

    def start(self):
        if not self._recording:
            try:
                self._ffmpeg = subprocess.Popen(self.ffmpeg_cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            except:
                raise

            stdout_peek = self._ffmpeg.stdout.peek(10)
            if not stdout_peek:
                raise RuntimeError("ffmpeg cmd doesn't return any data")
            self._recording = True
            self._start_timer()
            self._start_reader()
            self._start_stderr_reader()

    def _start_stderr_reader(self):
        self._stderr_thread = Thread(target=self._stderr_reader,args=())
        self._stderr_thread.daemon = True
        self._stderr_thread.start()
    def _stderr_reader(self):
        try:
            while self._recording:
                b = self._ffmpeg.stderr.read(100)
                if b:
                    print(b.decode('utf-8'))
        except Exception as e:
            print('stderr_reader: ',e)

    def _reader(self):
        try:
            while self._recording:
                self._lock.acquire()
                self._circ_buff.extend(self._ffmpeg.stdout.read(100))
                self._lock.release()

        except Exception as e:
            print(e)
    
    def cancel(self):
        if self._recording:
            self._timer.cancel()
            self._recording = False
            self._elapsed = 0.0
            self._ffmpeg.kill()
            self._reader_thread.join()
            self._stderr_thread.join()

    @property
    def np_circ_buff(self):
        self._lock.acquire()
        # '<i2': little endian 16-bit integer
        np_array = np.frombuffer(bytes(self._circ_buff),dtype='<i2')
        self._lock.release()
        return np_array

    def setDevice(self,device):
        pass
        #sd.default.device = device

    def query_devices(self):
        pulse = pulsectl.Pulse('client')
        sources = pulse.source_list()
        s_dict = [{'index':source.index,'name':source.proplist['alsa.long_card_name']} for source in sources]
        pulse.close()
        return s_dict

    def save(self,name,fold):
        if self._timer and self._recording:
            self._timer.cancel()
            self._recording = False
            self._elapsed = 0
            filename = f'{name}-{uuid.uuid4()}.wav'
            np_sample = self.np_circ_buff
            """self._sample[np.isnan(self._sample)] = 0
            self._sample[self._sample > 1] = 0
            self._sample[self._sample < -1] = 0"""
            sf.write(self.samples_path / filename,np_sample,samplerate=self._sample_rate,subtype='PCM_16')
            df = pd.read_csv(self.df_csv)
            s = pd.Series([filename,-1,name,fold],index=df_columns)
            df = pd.concat([df, s.to_frame().T])
            df.to_csv(self.df_csv,index=False)
            self._last = filename
            len = self._sample_duration * self._sample_rate
            x = np.linspace(0,self._sample_duration,len)
            return x.tolist(),np_sample.flatten().tolist()

if __name__ == "__main__":
    rec = Recorder('./datasets','4')
    code.interact(local=dict(globals(),**locals()))