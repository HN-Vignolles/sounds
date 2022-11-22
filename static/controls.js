let recording = false;

async function selectDevice(device) {
    const res = await fetch('/api/rec', {
        method: 'PUT',
        body: JSON.stringify({ 'action': 'device', 'index': device.id })
    });
    const json = await res.json();
    if (json['action'] === 'device') {
        $('#toggle').prop('disabled', false);
    }
    $('#input-device').html(json['device']['name']);
}

async function getTable(fold) {
    const res = await fetch('/api/table?' + new URLSearchParams({
        fold: fold.id
    }));
    const json = await res.json();
    if (json['table'] !== undefined) {
        $('#fold-span').html(json['fold'])
        makeTable('#df', json['table']);
    }
}

async function toggle() {
    let action;
    if (recording === false) {
        action = 'start'
    } else {
        action = 'cancel'
    }
    const res = await fetch('/api/rec', {
        method: 'PUT',
        body: JSON.stringify({ 'action': action })
    });
    const json = await res.json()
    if (json['action'] === 'start') {
        $('#toggle').text('Cancel');
        $('#toggle').removeClass('btn-success').addClass('btn-danger');
        recording = true;
    } else if (json['action'] === 'cancel') {
        $('#toggle').text('Start');
        $('#toggle').removeClass('btn-danger').addClass('btn-success');
        recording = false;
    }
}

async function save(element) {
    if (recording === true) {
        let fold;
        fold = $('#fold-input').val();
        fold = parseInt(fold || 1);

        const res = await fetch('/api/rec', {
            method: 'PUT',
            body: JSON.stringify({ 'action': 'save', 'event': element.id, 'fold': fold })
        });
        const json = await res.json()
        if (json['action'] === 'save') {
            $('#toggle').text('Start');
            $('#toggle').removeClass('btn-danger').addClass('btn-success');
            $('#fold-span').html(json['fold']);
            if (!folds.includes(fold)) {
                folds.push(fold);
                updateFolds('#fold-dropdown-div', folds, fold);
            }
            makeTable('#df', json['table']);
            makeAudioPlayer('#player',json['filename'])
            recording = false;
        }
        //Plotly.update('fig', { x: [json['x']], y: [json['y']] }, { xaxis: { ticksuffix: "s" } });
    }
}

function makeAudioPlayer(id,filename){
    let inner_html = '<figure><figcaption>Last sample: </figcaption>';
    inner_html += '<audio src="/datasets/' + filename + '" controls preload="auto"></audio></figure>';
    $(id).html(inner_html);
}

function makeTable(id, values) {
    let inner_html = '<table class="table table-sm small">';
    inner_html += '<thead><tr><th scope="col">Category</th><th scope="col">Samples</th></tr></thead>';
    inner_html += '<tbody>';
    values.forEach((e) => {
        inner_html += '<tr><td>' + e[0] + '</td><td>' + e[1] + '</td></tr>'
    });
    inner_html += '</tbody></table>';
    $(id).html(inner_html);
}

function updateFolds(id, values) {
    let inner_html = '<button class="btn btn-info dropdown-toggle" type="button" \
        id="fold-dropdown" data-toggle="dropdown" aria-haspopup="true" aria-expanded="false">Fold:</button>';
    inner_html += '<div class="dropdown-menu" aria-labelledby="devices">';
    values.forEach((e) => {
        inner_html += '<button class="dropdown-item" type="button" id="'
            + e + '" onclick="getTable(this)">' + e + '</button>';
    });
    inner_html += '</div><span id="fold-span" class="ml-2">' + fold + '</span>';
    $(id).html(inner_html);
}