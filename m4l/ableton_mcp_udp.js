// ableton_mcp_udp.js - Max for Live JS object
// Receives RMS/Peak values, sends JSON via UDP outlet

var rms_l_val = 0.0;
var rms_r_val = 0.0;
var peak_l_val = 0.0;
var peak_r_val = 0.0;

inlets = 4;   // 0=rms_l, 1=rms_r, 2=peak_l, 3=peak_r
outlets = 1;  // string -> udpsend

function msg_float(v) {
    if (inlet == 0) rms_l_val = v;
    else if (inlet == 1) { rms_r_val = v; sendJSON(); }
    else if (inlet == 2) peak_l_val = v;
    else if (inlet == 3) peak_r_val = v;
}

function bang() {
    sendJSON();
}

function ampToDB(amp) {
    if (amp <= 1e-10) return -999.0;
    return Math.round((20.0 * Math.log(amp) / Math.LN10) * 10.0) / 10.0;
}

function sendJSON() {
    var rms_mono = (rms_l_val + rms_r_val) / 2.0;
    var peak_mono = Math.max(peak_l_val, peak_r_val);
    var rms_db = ampToDB(rms_mono);
    var peak_db = ampToDB(peak_mono);
    var lufs = (rms_db > -998) ? Math.round((rms_db - 0.691) * 10) / 10 : -999.0;
    var ts = new Date().toISOString();

    var json = '{"timestamp":"' + ts + '","rms_db":' + rms_db +
               ',"peak_db":' + peak_db + ',"lufs_approx":' + lufs +
               ',"bands":{"sub":-999,"low":-999,"mid":-999,"high":-999,"air":-999}}';
    outlet(0, json);
}
