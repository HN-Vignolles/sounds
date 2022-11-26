#!/usr/bin/env python

from flask import Flask
from flask import send_from_directory, render_template, request
from flask_sock import Sock
import json
import os
from recorder import Recorder
from pathlib import Path
import pandas as pd
from config import samples_path, sound_events


app = Flask(__name__)
app.config.from_prefixed_env()  # e.g. FLASK_INPUT_FMT=lavfi ./app.py
app.config['SECRET_KEY'] = os.urandom(42)
app.config['SAMPLE_RATE'] = 16000
app.config['REC_DURATION'] = 2
sock = Sock(app)


if not samples_path.exists():
    samples_path.mkdir()

if os.name == 'posix':
    # options might be 'alsa' or 'pulse'
    input_format = 'alsa'
if os.name == 'nt':
    input_format = 'dshow'
input_format = app.config.get('INPUT_FMT') or input_format
ffmpeg_path = app.config.get('FFMPEG_BIN') or '/usr/bin/ffmpeg'


rec = Recorder(samples_path,ffmpeg_path,input_format,
               rec_duration=app.config.get('REC_DURATION'),
               sample_rate=app.config.get('SAMPLE_RATE'))
devices = rec.query_devices()


@app.route('/')
def base():
    df = pd.read_csv(samples_path / 'samples.csv')
    folds = set(df['fold'])
    table = []
    return render_template('index.html',
                           events=sound_events,
                           devices=devices,
                           table=table,
                           folds=folds)


@sock.route('/ws')
def handle(ws):
    try:
        while True:
            # data = ws.receive()
            if rec.is_recording():
                chunk = rec.decoded_chunk
                if chunk:
                    ws.send(json.dumps({'roll':chunk}))

    except Exception as e:
        print(e)
    return ''


@app.route('/datasets/<path:name>')
def send_sample(name):
    return send_from_directory(samples_path,name)


@app.route('/api/info')
def get_media_info():
    data = {
        'atr':rec.atr,
        'dcs':rec.decoded_chunk_size,
        'x':rec.x
    }
    return data


@app.route('/api/table')
def get_table():
    fold = request.args.get('fold')
    table = getTable(samples_path / 'samples.csv',fold)
    return {'fold':fold,'table':table}


@app.route('/api/rec',methods=['PUT'])
def apiRec():
    action = request.get_json(force=True)['action']
    if action == 'start':
        try:
            rec.start()
            return {'action':'start'}
        except Exception as e:
            return str(e),500

    elif action == 'device':
        # select device
        device_index = request.get_json(force=True)['index']
        device = [i for i in devices if i['index'] == device_index][0]
        rec.setDevice(device['input_dev'])
        return {'device':device}

    elif action == 'cancel':
        rec.cancel()
        return {'action':'cancel'}

    elif action == 'save':
        req = request.get_json(force=True)
        name = req.get('event', 'unnamed-event')
        fold = req.get('fold', '1') or '1'
        filename = rec.save(name,fold)
        table = getTable(samples_path / 'samples.csv', fold)
        return {'filename':filename, 'table':table, 'fold':fold}

    else:
        return "Bad request",400


def getTable(filename,fold):
    df = pd.read_csv(filename)
    balance = df[df.fold.isin([int(fold)])]['category'].value_counts()
    table = [s.split() for s in balance.to_string().split('\n')]
    return table


if __name__ == "__main__":
    app.run(debug=True)
    rec.cancel()
