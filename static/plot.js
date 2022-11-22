let socket = new WebSocket('ws://' + window.location.host + '/ws');
let first_chunk_time = 0;
let total_bytes = 0;
let Y = [];

async function initCanvas(id) {
    let fig = document.getElementById(id);
    let ctx = fig.getContext('2d');
    let cw = fig.width = 500;
    let ch = fig.height = 180;

    let media = await getMediaInfo();
    let chunkLength = media['dcs'];
    let X = media['x'];
    let xLength = X.length;
    let xStep = cw / xLength;
    let yAxisPos = ch / 2;
    let yScale = ch / 65536;

    function drawAxes() {
        ctx.beginPath();
        ctx.moveTo(cw, yAxisPos);
        ctx.lineTo(0, yAxisPos);
        ctx.stroke();
    }
    function plot(Y) {
        let x = 0;
        ctx.clearRect(0, 0, cw, ch);
        ctx.strokeStyle = 'rgba(21,71,52,0.5)'
        //drawAxes();
        ctx.beginPath();
        ctx.moveTo(0, yAxisPos - yScale * Y[0]);
        for (let i = 0; i < Y.length; i += 10) {
            ctx.lineTo(x, yAxisPos - yScale * Y[i])
            x += xStep * 10;
        }
        ctx.stroke();
    }

    socket.onmessage = event => {
        message = JSON.parse(event.data);
        if (message['roll'] !== undefined) {
            if (first_chunk_time === 0) {
                first_chunk_time = (new Date()).getTime() / 1000;
            }
            tailY = message['roll'];
            if (Y.length >= xLength) {
                Y.splice(0, chunkLength);
            }
            Y.push(...tailY);
            total_bytes += chunkLength * 2
        }
    };
    setInterval(() => {
        if (recording === true) {
            plot(Y);
        }
    }, 20);
}
initCanvas('roll');


async function getMediaInfo() {
    const res = await fetch('/api/info');
    const json = await res.json();
    // X: linspace
    // dcs: decoded chunk size
    // atr: average transfer rate (backend)
    return json;
}

/* setInterval(() => {
    if (recording === true) {
        now = (new Date()).getTime() / 1000;
        delta_t = now - first_chunk_time;
        average = (total_bytes / delta_t) / 1024;
        //console.log(`average transfer rate: ${average}`);
        //Plotly.update('fig',{ x:[X],y:[Y] },{});
    }
}, 250); */