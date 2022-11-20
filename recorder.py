import code
import sys,time,os
import subprocess
import uuid
from collections import deque
from struct import unpack
from pathlib import Path
from threading import Lock, Thread, Timer

import numpy as np
import pandas as pd
import soundfile as sf


df_columns = ['filename','target','category','fold']
pd.set_option('max_colwidth',None)


class RecorderBase():
    def __init__(self,rec_duration,sample_rate):
        self._rec_duration = rec_duration
        self._sample_rate = sample_rate
        self._last = ''
        self._recording = False
        self._elapsed = 0.0
        self._timer = None

    def _start_timer(self):
        self._timer = Timer(0.1,self._start_timer)
        self._timer.start()
        self._elapsed += 0.1
    
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
        return self._recording

    @property
    def elapsed(self):
        return self._elapsed


class Recorder(RecorderBase):
    def __init__(self,data_path,input,
                 rec_duration=2,sample_rate=44100,format='s16le'):
        super().__init__(rec_duration,sample_rate)

        if not input:
            raise ValueError("input must be supplied")
        if not data_path:
            raise ValueError("data_path must be supplied")
        if format not in ['s16le']:
            # TODO: add 'f32le'
            raise ValueError(f"{format} not implemented yet")
        
        self._format = format
        len = self._rec_duration * self._sample_rate
        self._bytes_per_sample = 2   # 2: bytes per sample (s16le)
        self._chunk_size = 100
        out_buff_size = (self._sample_rate * self._bytes_per_sample) // self._chunk_size
        self._unpack_str = f'<{self._chunk_size//self._bytes_per_sample}h'
        self._total_bytes = 0

        # _circ_buff holds last `rec_duration` of captured audio
        self._circ_buff = deque(maxlen=len * self._bytes_per_sample)
        
        # queue, to send chunks of chunk_size//2 to display captured audio in "roll mode"
        self._out_buff = deque(maxlen=out_buff_size*2)   # 2: safe margin
        
        # array x for plotting the waveform:
        self.x = np.linspace(0,self._rec_duration,len).tolist()

        # '-f lavfi -i "sine=frequency=880"'
        self._input_fmt = input['format']
        self._input_dev = input['device']
        self._input_dev_str = f"-f {self._input_fmt} -ac 1 -i {self._input_dev}"
        self.ffmpeg_cmd = f"/usr/bin/ffmpeg -re {self._input_dev_str} \
                            -ar {sample_rate} -ac 1 -f {self._format} -blocksize 1000 -flush_packets 1 -".split()
        self._lock = Lock()
        self.data_path = Path(data_path)
        self.df_csv = self.data_path / 'samples.csv'
        if not self.df_csv.exists():
            df = pd.DataFrame(columns=df_columns)
            df.to_csv(self.df_csv,index=False)

    def start(self):
        if not self._recording:
            try:
                self._ffmpeg = subprocess.Popen(self.ffmpeg_cmd,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
            except:
                raise

            stdout_peek = self._ffmpeg.stdout.peek(10)
            if not stdout_peek:
                raise RuntimeError("ffmpeg cmd doesn't return any data")
            self._recording = True
            self._start_timer()
            self._start_reader()
            #self._start_stderr_reader()

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
        self._reader_start_t = time.time()
        try:
            while self._recording:
                #self._lock.acquire()
                data = self._ffmpeg.stdout.read(self._chunk_size)
                self._total_bytes += self._chunk_size
                self._circ_buff.extend(data)
                self._out_buff.append(data)
                #self._lock.release()

        except Exception as e:
            print(e)
    
    def cancel(self):
        if self._recording:
            self._timer.cancel()
            self._recording = False
            self._elapsed = 0.0
            self._total_bytes = 0
            self._ffmpeg.kill()
            self._reader_thread.join()
            #self._stderr_thread.join()

    @property
    def np_circ_buff(self):
        """returns the content of the circular buffer as a 1D numpy array"""
        # '<i2': little endian 16-bit integer
        np_array = np.frombuffer(bytes(self._circ_buff),dtype='<i2')
        return np_array

    @property
    def decoded_queue(self):
        #self._lock.acquire()
        try:
            return unpack(self._unpack_str,self._out_buff.popleft())
        except:
            return None
        #self._lock.release()

    @property
    def decoded_chunk_size(self):
        return self._chunk_size//self._bytes_per_sample

    @property
    def xy_buff(self):
        np_array = self.np_circ_buff
        return self.x,np_array.flatten().tolist()

    @property
    def atr(self):
        """average transfer rate"""
        # average transfer rate should be about 31.2KiB/s @sample_rate=16000;s16le
        #                                       86.1KiB/s @sample_rate=44100;s16le
        delta_t = time.time() - self._reader_start_t
        return round((self._total_bytes/delta_t)/1024,2)

    def setDevice(self,device):
        pass
        #sd.default.device = device

    def query_devices(self):
        if self._input_fmt == 'pulse':
            import pulsectl
            pulse = pulsectl.Pulse('client')
            sources = pulse.source_list()
            s_dict = [{'index':f'{source.index}','name':source.proplist['alsa.long_card_name']} for source in sources]
            pulse.close()
            return s_dict
        elif self._input_fmt == 'alsa':
            import re
            arecordl = subprocess.Popen(['arecord','-l'],stdout=subprocess.PIPE)
            s_dict = []
            index = 0
            for line in arecordl.stdout.readlines():
                s = re.match('card ([0-9]+).*?\[([^\]]*)].*?device ([0-9]+).*?\[([^\]]*)]',line.decode('utf-8'),re.IGNORECASE)
                if s:
                    s_dict.append({'index':f'{index}','hw':f'hw:{s.group(1)},{s.group(3)}','name':f'{s.group(2)} - {s.group(4)}'})
                    index += 1
            return s_dict

    def save(self,name,fold):
        if self._timer and self._recording:
            self._timer.cancel()
            self._recording = False
            self._elapsed = 0
            filename = f'{name}-{uuid.uuid4()}.wav'
            np_sample = self.np_circ_buff
            sf.write(self.data_path / filename,np_sample,samplerate=self._sample_rate,subtype='PCM_16')
            df = pd.read_csv(self.df_csv)
            s = pd.Series([filename,-1,name,fold],index=df_columns)
            df = pd.concat([df, s.to_frame().T])
            df.to_csv(self.df_csv,index=False)
            self._last = filename
            return self.xy_buff

if __name__ == "__main__":
    rec = Recorder('./datasets',{'format':'pulse','device':1})
    #code.interact(local=dict(globals(),**locals()))
    #print(rec.query_devices())
    rec.start()
    while True:
        try:
            out = rec._out_buff.popleft()
            #sys.stdout.buffer.write(out)
            if round(rec.elapsed,2) % 1 == 0:
                    ...
                    print(f'average transfer rate: {rec.atr}',end='\r',flush=True)
                    #print('{:.04f}'.format(self._elapsed),end='\n',flush=True)
        except:
            pass
