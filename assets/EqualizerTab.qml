pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import Quickshell.Io
import Caelestia.Config
import qs.components
import qs.components.controls
import qs.services

Item {
    id: root

    implicitWidth: 840
    implicitHeight: 570

    property var bands: []
    property bool ready: false
    property bool bypass: false
    property bool globalBypass: false
    property bool busy: false
    property string status: qsTr("Checking EasyEffects…")
    property string activePreset: "Custom"
    readonly property var presetNames: ["Flat", "Bass Boost", "Deep Bass", "Treble Boost", "Vocal", "Podcast", "Electronic", "Rock", "Classical", "Gaming", "Night Listening"]
    readonly property var shapes: [
        [0,0,0,0,0,0,0,0,0,0], [5,5,4,3,1,0,0,0,0,0], [8,7,6,4,2,0,-1,-1,-2,-2],
        [-1,-1,-1,0,0,1,2,3,4,5], [-3,-2,-1,0,2,3,3,2,0,-1], [-4,-3,-2,0,2,4,3,1,-1,-2],
        [5,4,2,0,-1,0,2,3,3,2], [4,3,1,-1,0,2,3,2,1,0], [0,0,-0.5,-0.5,0,0.5,0.5,0.5,0,0],
        [4,3,1,-1,0,2,3,2,1,1], [-5,-4,-3,-2,-1,0,0,-1,-2,-3]
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
    ListModel { id: bandModel }
    property var pending: []
    property var dirtyBands: ({})
    property int revision: 0
    property int requestRevision: 0
    property int dragging: 0
    property bool received: false
    property bool initialized: false
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
        helper.command = ["python3", Qt.resolvedUrl("sound/easyeffects.py").toString().replace(/^file:\/\//, ""), ...args];
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

    Component.onCompleted: {
        initialized = true;
        refresh();
    }
    onVisibleChanged: if (initialized && visible) refresh()
    Timer { id: saveTimer; interval: 100; onTriggered: root.save() }
    Timer {
        interval: 12000
        repeat: true
        running: root.visible
        onTriggered: root.refresh()
    }

    Process {
        id: helper
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

    Loader {
        id: controlsLoader
        anchors.fill: parent
        asynchronous: true

        sourceComponent: ColumnLayout {
            anchors.fill: parent
            spacing: Tokens.spacing.medium

            RowLayout {
                Layout.fillWidth: true
                Layout.leftMargin: Tokens.padding.large
                Layout.rightMargin: Tokens.padding.large
                ColumnLayout {
                    spacing: Tokens.spacing.extraSmall
                    StyledText {
                        text: qsTr("Equalizer")
                        font: Tokens.font.body.builders.large.size(28).weight(Font.DemiBold).build()
                        color: Colours.palette.m3onSurface
                    }
                    StyledText {
                        text: qsTr("Make room for the sound you love")
                        color: Colours.palette.m3onSurfaceVariant
                    }
                }
                Item { Layout.fillWidth: true }
                StyledText {
                    text: !root.ready ? root.status : root.busy || saveTimer.running ? qsTr("Saving…") : root.audible ? qsTr("●  Live · EasyEffects") : qsTr("○  Bypassed")
                    color: root.ready && !root.bypass && !root.globalBypass ? Colours.palette.m3primary : Colours.palette.m3onSurfaceVariant
                    wrapMode: Text.WordWrap
                    Layout.maximumWidth: 310
                    horizontalAlignment: Text.AlignRight
                }
            }

            StyledRect {
                Layout.fillWidth: true
                Layout.fillHeight: true
                radius: Tokens.rounding.extraLarge
                color: Colours.tPalette.m3surfaceContainer

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: Tokens.padding.large
                    spacing: Tokens.spacing.medium

                    RowLayout {
                        Layout.fillWidth: true
                        StyledText {
                            text: qsTr("Output equalizer")
                            font: Tokens.font.body.builders.large.weight(Font.DemiBold).build()
                            color: Colours.palette.m3onSurface
                        }
                        Item { Layout.fillWidth: true }
                        StyledText {
                            text: root.ready ? (root.bypass ? qsTr("Off") : qsTr("On")) : ""
                            color: Colours.palette.m3onSurfaceVariant
                        }
                        StyledSwitch {
                            disabled: !root.ready
                            checked: root.ready && !root.bypass
                            onClicked: { root.revision++; root.bypass = !checked; root.run(["enabled", checked ? "true" : "false"]); }
                            Accessible.name: qsTr("Enable output equalizer")
                        }
                    }

                    StyledText {
                        visible: !root.ready || root.globalBypass || root.bypass
                        text: !root.ready ? qsTr("Add an Equalizer to the EasyEffects output chain and start EasyEffects, then retry.") :
                              root.globalBypass ? qsTr("EasyEffects global bypass is on. Turn it off in EasyEffects to hear this equalizer.") :
                              qsTr("The equalizer is bypassed. Turn it on to hear changes.")
                        color: Colours.palette.m3onSurfaceVariant
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                    }

                    Item {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 58
                        opacity: root.audible ? 1 : 0.45
                        Behavior on opacity { Anim {} }
                        Canvas {
                            id: curve
                            anchors.fill: parent
                            property color lineColor: Colours.palette.m3primary
                            property color gridColor: Qt.alpha(Colours.palette.m3onSurfaceVariant, 0.16)
                            onLineColorChanged: requestPaint()
                            onGridColorChanged: requestPaint()
                            onWidthChanged: requestPaint()
                            onHeightChanged: requestPaint()
                            onPaint: {
                                const ctx = getContext("2d");
                                ctx.reset();
                                ctx.strokeStyle = gridColor;
                                ctx.lineWidth = 1;
                                ctx.setLineDash([3, 5]);
                                ctx.beginPath(); ctx.moveTo(0, height / 2); ctx.lineTo(width, height / 2); ctx.stroke();
                                ctx.setLineDash([]);
                                const points = [];
                                for (let i = 0; i < sliders.count; i++) {
                                    const item = sliders.itemAt(i);
                                    if (item) points.push({x: (i + 0.5) * width / sliders.count,
                                        y: height / 2 - item.visualGain / 12 * (height / 2 - 5)});
                                }
                                if (!points.length) return;
                                function trace() {
                                    ctx.moveTo(0, points[0].y);
                                    ctx.lineTo(points[0].x, points[0].y);
                                    for (let i = 1; i < points.length; i++) {
                                        const a = points[i - 1], b = points[i], middle = (a.x + b.x) / 2;
                                        ctx.bezierCurveTo(middle, a.y, middle, b.y, b.x, b.y);
                                    }
                                    ctx.lineTo(width, points[points.length - 1].y);
                                }
                                ctx.beginPath(); trace();
                                ctx.lineTo(width, height); ctx.lineTo(0, height); ctx.closePath();
                                const fill = ctx.createLinearGradient(0, 0, 0, height);
                                fill.addColorStop(0, Qt.alpha(lineColor, 0.24));
                                fill.addColorStop(1, Qt.alpha(lineColor, 0));
                                ctx.fillStyle = fill; ctx.fill();
                                ctx.beginPath(); trace(); ctx.strokeStyle = lineColor; ctx.lineWidth = 2; ctx.stroke();
                            }
                        }
                    }

                    Flickable {
                        id: bandView
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        Layout.minimumHeight: 150
                        contentWidth: Math.max(width, bandRow.implicitWidth)
                        contentHeight: height
                        flickableDirection: Flickable.HorizontalFlick
                        boundsBehavior: Flickable.StopAtBounds
                        interactive: contentWidth > width && root.dragging === 0
                        clip: true
                        Controls.ScrollBar.horizontal: Controls.ScrollBar {}

                        RowLayout {
                            id: bandRow
                            width: Math.max(bandView.width, implicitWidth)
                            height: bandView.height
                            spacing: 2
                            Repeater {
                                id: sliders
                                model: bandModel
                                delegate: ColumnLayout {
                                    id: bandColumn
                                    required property int index
                                    required property real frequency
                                    required property real gain
                                    property real visualGain: gain
                                    onVisualGainChanged: curve.requestPaint()
                                    Behavior on visualGain { enabled: !bandSlider.pressed; Anim { type: Anim.FastSpatial } }
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    Layout.minimumWidth: 48
                                    spacing: 3

                                    StyledText {
                                        Layout.alignment: Qt.AlignHCenter
                                        text: (bandColumn.visualGain >= 0.05 ? "+" : "") + (Math.abs(bandColumn.visualGain) < 0.05 ? "0.0" : bandColumn.visualGain.toFixed(1))
                                        color: bandSlider.pressed || bandSlider.hovered ? Colours.palette.m3primary : Colours.palette.m3onSurface
                                        font.bold: bandSlider.pressed
                                    }
                                    Controls.Slider {
                                        id: bandSlider
                                        Layout.fillHeight: true
                                        Layout.preferredWidth: 44
                                        Layout.alignment: Qt.AlignHCenter
                                        orientation: Qt.Vertical
                                        from: -12
                                        to: 12
                                        stepSize: 0.1
                                        value: bandColumn.gain
                                        enabled: root.ready
                                        hoverEnabled: true
                                        focusPolicy: Qt.StrongFocus
                                        wheelEnabled: true
                                        onPressedChanged: {
                                            root.dragging += pressed ? 1 : -1;
                                            if (!pressed) root.save();
                                        }
                                        onMoved: root.preview(bandColumn.index, value)
                                        Keys.onEscapePressed: focus = false
                                        Keys.onSpacePressed: root.preview(bandColumn.index, 0)
                                        Accessible.name: qsTr("%1 Hz gain. Space to reset.").arg(Math.round(bandColumn.frequency))
                                        Controls.ToolTip.visible: hovered && !pressed
                                        Controls.ToolTip.delay: 700
                                        Controls.ToolTip.text: qsTr("Scroll or use arrow keys · Space to reset")

                                        background: Rectangle {
                                            x: bandSlider.leftPadding + (bandSlider.availableWidth - width) / 2
                                            y: bandSlider.topPadding + bandSlider.handle.height / 2
                                            width: 6
                                            height: Math.max(0, bandSlider.availableHeight - bandSlider.handle.height)
                                            radius: 3
                                            color: Colours.palette.m3surfaceContainerHighest
                                            Rectangle {
                                                width: parent.width
                                                y: Math.min(parent.height / 2, (1 - (bandColumn.visualGain + 12) / 24) * parent.height)
                                                height: Math.abs(bandColumn.visualGain) / 24 * parent.height
                                                radius: 3
                                                color: Colours.palette.m3primary
                                                opacity: root.audible ? 0.8 : 0.35
                                            }
                                            Rectangle {
                                                anchors.centerIn: parent
                                                width: 14; height: 2; radius: 1
                                                color: Colours.palette.m3outline
                                            }
                                        }
                                        handle: Rectangle {
                                            x: bandSlider.leftPadding + (bandSlider.availableWidth - width) / 2
                                            y: bandSlider.topPadding + (1 - (bandColumn.visualGain + 12) / 24) * (bandSlider.availableHeight - height)
                                            width: 28; height: 16; radius: 8
                                            scale: bandSlider.pressed ? 1.18 : bandSlider.hovered ? 1.08 : 1
                                            color: Colours.palette.m3primary
                                            border.width: bandSlider.activeFocus ? 2 : 0
                                            border.color: Colours.palette.m3onSurface
                                            Rectangle {
                                                anchors.centerIn: parent
                                                width: 10; height: 2; radius: 1
                                                color: Colours.palette.m3onPrimary
                                            }
                                            Behavior on scale { Anim { type: Anim.FastSpatial } }
                                        }
                                    }
                                    StyledText {
                                        Layout.alignment: Qt.AlignHCenter
                                        text: bandColumn.frequency >= 1000 ? (bandColumn.frequency / 1000).toFixed(bandColumn.frequency % 1000 ? 1 : 0) + "k" : String(Math.round(bandColumn.frequency))
                                        color: Colours.palette.m3onSurfaceVariant
                                    }
                                }
                            }
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        StyledText { text: qsTr("BASS"); color: Colours.palette.m3onSurfaceVariant; font.pointSize: 9 }
                        Item { Layout.fillWidth: true }
                        StyledText { text: qsTr("MID"); color: Colours.palette.m3onSurfaceVariant; font.pointSize: 9 }
                        Item { Layout.fillWidth: true }
                        StyledText { text: qsTr("TREBLE  ·  ±12 dB"); color: Colours.palette.m3onSurfaceVariant; font.pointSize: 9 }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        StyledText {
                            text: qsTr("Preset: %1").arg(root.activePreset)
                            color: Colours.palette.m3onSurface
                        }
                        Item { Layout.fillWidth: true }
                        TextButton {
                            text: qsTr("Reset to flat")
                            disabled: !root.ready
                            onClicked: root.selectPreset(0)
                        }
                        TextButton {
                            text: qsTr("Reconnect")
                            disabled: root.busy
                            onClicked: root.refresh()
                        }
                    }
                    Flow {
                        Layout.fillWidth: true
                        Layout.preferredHeight: implicitHeight
                        spacing: 6
                        Repeater {
                            model: root.presetNames
                            delegate: TextButton {
                                required property int index
                                required property string modelData
                                text: modelData
                                type: TextButton.Tonal
                                checked: root.activePreset === modelData
                                disabled: !root.ready
                                verticalPadding: 7
                                onClicked: root.selectPreset(index)
                                Accessible.name: qsTr("%1 preset").arg(modelData)
                                Behavior on color { CAnim {} }
                            }
                        }
                    }
                }
            }
        }
    }
}
