pragma Singleton

import QtQuick
import Quickshell.Io

QtObject {
    id: root

    property var bands: []
    property bool ready: false
    property bool bypass: false
    property bool globalBypass: false
    property bool busy: false
    property string status: qsTr("Checking EasyEffects…")
    property string activePreset: "Custom"
    readonly property var presetNames: ["Flat", "Bass Boost", "Deep Bass", "Treble Boost", "Vocal", "Electronic", "Rock", "Classical", "Night Listening"]
    readonly property var shapes: [
        [0,0,0,0,0,0,0,0,0,0], [5,5,4,3,1,0,0,0,0,0], [8,7,6,4,2,0,-1,-1,-2,-2],
        [-1,-1,-1,0,0,1,2,3,4,5], [-3,-2,-1,0,2,3,3,2,0,-1],
        [5,4,2,0,-1,0,2,3,3,2], [4,3,1,-1,0,2,3,2,1,0], [0,0,-0.5,-0.5,0,0.5,0.5,0.5,0,0],
        [-5,-4,-3,-2,-1,0,0,-1,-2,-3]
    ]
    readonly property var anchorsHz: [31,62,125,250,500,1000,2000,4000,8000,16000]

    function gainsFor(presetIndex) {
        const shape = shapes[presetIndex];
        return bands.map(b => {
            const frequency = Math.max(31, Math.min(16000, b.frequency));
            let j = 0;
            while (j < 9 && frequency > anchorsHz[j + 1]) j++;
            if (j === 9) return shape[9];
            const t = Math.log(frequency / anchorsHz[j]) / Math.log(anchorsHz[j + 1] / anchorsHz[j]);
            return Math.round((shape[j] + (shape[j + 1] - shape[j]) * t) * 10) / 10;
        });
    }

    function matchPreset() {
        for (let p = 0; p < presetNames.length; p++) {
            const gains = gainsFor(p);
            if (gains.every((gain, i) => Math.abs(gain - bands[i].gain) < 0.06)) return presetNames[p];
        }
        return "Custom";
    }

    // Keep delegates alive while synchronizing, so dragging and focus survive replies.
    readonly property ListModel bandModel: ListModel {}
    property var pending: []
    property var dirtyBands: ({})
    property int revision: 0
    property int requestRevision: 0
    property int dragging: 0
    property bool received: false
    readonly property bool audible: ready && !bypass && !globalBypass

    function localBands() {
        const values = [];
        for (let i = 0; i < bandModel.count; i++) {
            const band = bandModel.get(i);
            values.push({frequency: band.frequency, gain: band.gain});
        }
        bands = values;
        activePreset = matchPreset();
    }

    function run(args) {
        // Coalesce edits by band, while preserving edits to different bands.
        if (args[0] === "gains") {
            const previous = pending.find(item => item[0] === "gains");
            const changes = Object.assign({}, previous ? JSON.parse(previous[1]) : {}, JSON.parse(args[1]));
            pending = pending.filter(item => item[0] !== "gains");
            pending = [...pending, ["gains", JSON.stringify(changes)]];
        } else if (args[0] === "preset") {
            // A new preset supersedes all earlier band edits and presets.
            pending = pending.filter(item => item[0] !== "gains" && item[0] !== "preset");
            pending = [...pending, args];
        } else {
            pending = pending.filter(item => item[0] !== args[0]);
            pending = [...pending, args];
        }
        dispatchNext();
    }

    function dispatchNext() {
        if (busy || !pending.length) return;
        const args = pending[0];
        pending = pending.slice(1);
        busy = true;
        received = false;
        requestRevision = revision;
        helper.command = ["python3", Qt.resolvedUrl("../sound/easyeffects.py").toString().replace(/^file:\/\//, ""), ...args];
        helper.running = true;
    }

    function refresh() { if (!busy && !dragging && !saveTimer.running) run(["snapshot"]); }
    function preview(index, gain) {
        const rounded = Math.round(gain * 10) / 10;
        if (Math.abs(bandModel.get(index).gain - rounded) < 0.05) return;
        revision++;
        bandModel.setProperty(index, "gain", rounded);
        dirtyBands = Object.assign({}, dirtyBands, {[index]: rounded});
        localBands();
        saveTimer.restart();
    }
    function save() {
        saveTimer.stop();
        if (!ready || !Object.keys(dirtyBands).length) return;
        const changes = dirtyBands;
        dirtyBands = ({});
        run(["gains", JSON.stringify(changes)]);
    }
    function selectPreset(index) {
        if (!ready) return;
        saveTimer.stop();
        dirtyBands = ({});
        revision++;
        const values = gainsFor(index);
        for (let i = 0; i < values.length; i++) bandModel.setProperty(i, "gain", values[i]);
        localBands();
        run(["preset", JSON.stringify(values)]);
    }

    function setEnabled(enabled) {
        revision++;
        bypass = !enabled;
        run(["enabled", enabled ? "true" : "false"]);
    }

    readonly property Timer saveTimer: Timer { interval: 100; onTriggered: root.save() }

    readonly property Process helper: Process {
        stdout: StdioCollector {
            onStreamFinished: {
                root.received = true;
                try {
                    const result = JSON.parse(text);
                    root.ready = result.ready === true;
                    root.status = result.status || qsTr("No response from EasyEffects");
                    if (root.ready && root.revision === root.requestRevision && !root.dragging && !root.pending.length && !Object.keys(root.dirtyBands).length) {
                        if (bandModel.count !== result.bands.length) {
                            bandModel.clear();
                            bandModel.append(result.bands);
                        } else {
                            for (let i = 0; i < result.bands.length; i++) bandModel.set(i, result.bands[i]);
                        }
                        root.localBands();
                        root.bypass = result.bypass;
                        root.globalBypass = result.globalBypass;
                    }
                } catch (error) {
                    root.ready = false;
                    root.status = qsTr("Could not read EasyEffects response");
                }
            }
        }
        onExited: (exitCode, exitStatus) => {
            root.busy = false;
            if (exitCode !== 0 || !root.received) {
                root.ready = false;
                root.status = qsTr("EasyEffects helper failed. Try reconnecting.");
            }
            if (!root.ready) {
                root.pending = [];
                root.dirtyBands = ({});
                saveTimer.stop();
            } else {
                // Keep the queue intact until dispatch, including edits arriving
                // between this exit signal and the next event-loop iteration.
                Qt.callLater(root.dispatchNext);
            }
        }
    }
}
