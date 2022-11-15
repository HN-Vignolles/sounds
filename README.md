Tool for making small sound datasets. Once the recording backend starts, it can record fixed-length audio; and then update a data frame in CSV format. `sounddevice` is being used as a recording backend

# Install
```bash
pip install -r requirements.txt
```

# Run
```bash
python app.py
```

# TODO
- switch to `ffmpeg` backend
- https://github.com/marketplace/actions/setup-ffmpeg
- c.f. https://github.com/smirnov-am/flask-streaming