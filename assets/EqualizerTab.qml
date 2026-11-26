pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Effects
import QtQuick.Layouts
import QtQuick.Controls as Controls
import Caelestia.Config
import qs.components
import qs.components.controls
import qs.services
import "equalizer"

Item {
    id: root

    implicitWidth: 840
    implicitHeight: 520

    readonly property EqualizerState equalizer: EqualizerState
    property color surfaceColor: Colours.tPalette.m3surfaceContainer
    property bool controlsActive: visible
    property int dragging: 0
    property bool initialized: false
    signal presetApplied()

    function selectPreset(index) {
        if (!equalizer.ready) return;
        equalizer.selectPreset(index);
        presetApplied();
    }

    Component.onCompleted: {
        initialized = true;
        if (controlsActive) equalizer.refresh();
    }
    Component.onDestruction: {
        if (dragging) {
            equalizer.dragging -= dragging;
            equalizer.save();
        }
    }
    onControlsActiveChanged: if (initialized && controlsActive) equalizer.refresh()

    Timer {
        interval: 12000
        repeat: true
        running: root.controlsActive
        onTriggered: root.equalizer.refresh()
    }

    Loader {
        id: controlsLoader
        anchors.fill: parent
        asynchronous: true

        sourceComponent: ColumnLayout {
            anchors.fill: parent
            spacing: Tokens.spacing.medium

            StyledRect {
                Layout.fillWidth: true
                Layout.fillHeight: true
                radius: Tokens.rounding.extraLarge
                color: root.surfaceColor

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
                            visible: root.equalizer.ready
                            text: root.equalizer.bypass ? qsTr("Off") : qsTr("On")
                            color: Colours.palette.m3onSurfaceVariant
                        }
                        StyledSwitch {
                            disabled: !root.equalizer.ready
                            checked: root.equalizer.ready && !root.equalizer.bypass
                            onClicked: root.equalizer.setEnabled(checked)
                            Accessible.name: qsTr("Enable output equalizer")
                            Controls.ToolTip.visible: hovered
                            Controls.ToolTip.delay: 500
                            Controls.ToolTip.text: Accessible.name
                        }
                    }

                    StyledText {
                        visible: !root.equalizer.ready || root.equalizer.globalBypass
                        text: !root.equalizer.ready ? root.equalizer.status : qsTr("Turn off global bypass in EasyEffects to hear the equalizer.")
                        color: Colours.palette.m3onSurfaceVariant
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                    }

                    Item {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 58
                        opacity: root.equalizer.audible ? 1 : 0.45
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
                                model: root.equalizer.bandModel
                                onItemAdded: curve.requestPaint()
                                onItemRemoved: curve.requestPaint()
                                delegate: ColumnLayout {
                                    id: bandColumn
                                    required property int index
                                    required property real frequency
                                    required property real gain
                                    property real visualGain: gain
                                    readonly property Item knobItem: knob
                                    readonly property Item railItem: rail
                                    readonly property real pulse: presetLightning.pulseAt(index)
                                    readonly property real strike: presetLightning.strikeAt(index)
                                    onVisualGainChanged: curve.requestPaint()
                                    Behavior on visualGain {
                                        enabled: !bandSlider.pressed
                                        NumberAnimation { duration: 350; easing.type: Easing.OutQuart }
                                    }
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
                                        enabled: root.equalizer.ready
                                        hoverEnabled: true
                                        focusPolicy: Qt.StrongFocus
                                        wheelEnabled: true
                                        onPressedChanged: {
                                            root.dragging += pressed ? 1 : -1;
                                            root.equalizer.dragging += pressed ? 1 : -1;
                                            if (!pressed) {
                                                root.equalizer.save();
                                                releaseFlash.restart();
                                            }
                                        }
                                        onMoved: {
                                            root.equalizer.preview(bandColumn.index, value);
                                            movementPop.restart();
                                        }
                                        Keys.onEscapePressed: focus = false
                                        Keys.onSpacePressed: root.equalizer.preview(bandColumn.index, 0)
                                        Accessible.name: qsTr("%1 Hz gain. Space to reset.").arg(Math.round(bandColumn.frequency))
                                        Controls.ToolTip.visible: hovered && !pressed
                                        Controls.ToolTip.delay: 700
                                        Controls.ToolTip.text: qsTr("Scroll or use arrow keys · Space to reset")

                                        background: Rectangle {
                                            id: rail
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
                                                opacity: root.equalizer.audible ? 0.8 : 0.35
                                            }
                                            Rectangle {
                                                anchors.centerIn: parent
                                                width: 14; height: 2; radius: 1
                                                color: Colours.palette.m3outline
                                            }
                                            Item {
                                                y: (1 - (bandColumn.visualGain + 12) / 24) * parent.height
                                                width: parent.width
                                                height: parent.height - y
                                                clip: true
                                                visible: bandColumn.pulse < 1

                                                Rectangle {
                                                    anchors.fill: parent
                                                    color: presetLightning.accent
                                                    radius: 3
                                                    opacity: (1 - bandColumn.pulse) * presetLightning.fade * 0.56
                                                }
                                                Rectangle {
                                                    readonly property real progress: 1 - (1 - bandColumn.pulse) ** 4
                                                    width: parent.width
                                                    height: 46
                                                    y: progress * (parent.height + height) - height
                                                    opacity: Math.min(1, 2 * Math.sin(progress * Math.PI)) * presetLightning.fade
                                                    gradient: Gradient {
                                                        GradientStop { position: 0; color: Qt.alpha(presetLightning.accent, 0) }
                                                        GradientStop { position: 0.5; color: presetLightning.core }
                                                        GradientStop { position: 1; color: Qt.alpha(presetLightning.accent, 0) }
                                                    }
                                                }
                                            }
                                        }
                                        handle: Rectangle {
                                            id: knob

                                            property real interactionScale: bandSlider.pressed ? 1.25 : bandSlider.hovered ? 1.08 : 1
                                            property real movementScale: 1
                                            property real flashOpacity: 0

                                            x: bandSlider.leftPadding + (bandSlider.availableWidth - width) / 2
                                            y: bandSlider.topPadding + (1 - (bandColumn.visualGain + 12) / 24) * (bandSlider.availableHeight - height)
                                            width: 28; height: 16; radius: 8
                                            scale: interactionScale * movementScale + bandColumn.strike * 0.4
                                            color: Qt.lighter(Colours.palette.m3primary, bandSlider.pressed ? 1.30 : bandSlider.hovered ? 1.15 : 1)
                                            border.width: bandSlider.activeFocus ? 2 : 0
                                            border.color: Colours.palette.m3onSurface
                                            Rectangle {
                                                anchors.centerIn: parent
                                                width: 10; height: 2; radius: 1
                                                color: Colours.palette.m3onPrimary
                                            }
                                            Rectangle {
                                                anchors.fill: parent
                                                radius: knob.radius
                                                color: presetLightning.core
                                                opacity: Math.max(knob.flashOpacity, (1 - bandColumn.pulse) * presetLightning.fade * 0.85)
                                            }

                                            Behavior on interactionScale {
                                                NumberAnimation { duration: 150; easing.type: Easing.OutBack }
                                            }
                                            Behavior on color { ColorAnimation { duration: 150 } }

                                            SequentialAnimation {
                                                id: movementPop
                                                NumberAnimation {
                                                    target: knob
                                                    property: "movementScale"
                                                    to: 1.12
                                                    duration: 100
                                                    easing.type: Easing.OutQuad
                                                }
                                                NumberAnimation {
                                                    target: knob
                                                    property: "movementScale"
                                                    to: 1
                                                    duration: 200
                                                    easing.type: Easing.OutCubic
                                                }
                                            }
                                            NumberAnimation {
                                                id: releaseFlash
                                                target: knob
                                                property: "flashOpacity"
                                                from: 0.35
                                                to: 0
                                                duration: 300
                                                easing.type: Easing.OutCubic
                                            }
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

                        Canvas {
                            id: presetLightning

                            // Keep the Canvas as wide as the viewport, even with 32 bands.
                            parent: bandView
                            anchors.fill: parent
                            z: -1
                            visible: presetSweep.running
                            layer.enabled: visible
                            layer.effect: MultiEffect {
                                shadowEnabled: true
                                shadowColor: presetLightning.accent
                                shadowBlur: 0.9
                                shadowOpacity: 0.7
                                shadowHorizontalOffset: 0
                                shadowVerticalOffset: 0
                            }

                            readonly property color accent: Colours.palette.m3primary
                            readonly property color core: Colours.palette.m3onSurface
                            readonly property real sweepDuration: 650
                            readonly property real holdUntil: sweepDuration + 150
                            readonly property real duration: holdUntil + 800
                            readonly property int span: lastBand - firstBand + 1
                            readonly property real reach: firstBand + span * Math.sin(Math.min(1, elapsed / sweepDuration) * Math.PI / 2)
                            readonly property real fade: Math.pow(1 - Math.max(0, elapsed - holdUntil) / (duration - holdUntil), 2)
                            readonly property var strands: [
                                { width: 15, opacity: 0.32, color: accent, amplitude: 15 },
                                { width: 7.5, opacity: 0.58, color: Qt.lighter(accent, 1.18), amplitude: 10 },
                                { width: 3.5, opacity: 0.8, color: Qt.lighter(accent, 1.3), amplitude: 5 }
                            ]
                            property int firstBand: 0
                            property int lastBand: -1
                            property real elapsed: 0

                            function play() {
                                if (!root.controlsActive || !bandView.width || !sliders.count) return;
                                const first = sliders.itemAt(0);
                                if (!first || !first.width) return;
                                const step = first.width + bandRow.spacing;
                                firstBand = Math.min(sliders.count - 1, Math.floor(bandView.contentX / step));
                                lastBand = Math.min(sliders.count - 1, Math.ceil((bandView.contentX + bandView.width) / step) - 1);
                                presetSweep.restart();
                                requestPaint();
                            }

                            function pulseAt(index) {
                                if (!presetSweep.running || index < firstBand || index > lastBand || index + 0.4 > reach) return 1;
                                const fraction = (index - firstBand + 0.4) / span;
                                const arrival = Math.asin(fraction) / (Math.PI / 2) * sweepDuration;
                                return Math.max(0, Math.min(1, (elapsed - arrival) / 1000));
                            }

                            function strikeAt(index) {
                                const distance = reach - index;
                                return presetSweep.running && index >= firstBand && index <= lastBand && distance > 0 && distance < 1
                                    ? Math.sin(distance * Math.PI) * fade : 0;
                            }

                            onElapsedChanged: requestPaint()

                            NumberAnimation {
                                id: presetSweep
                                target: presetLightning
                                property: "elapsed"
                                from: 0
                                to: presetLightning.duration
                                duration: presetLightning.duration
                            }

                            Connections {
                                target: root
                                function onPresetApplied() { presetLightning.play(); }
                                function onControlsActiveChanged() { if (!root.controlsActive) presetSweep.stop(); }
                            }

                            onPaint: {
                                const ctx = getContext("2d");
                                ctx.clearRect(0, 0, width, height);
                                if (!presetSweep.running) return;

                                const points = [];
                                ctx.lineCap = "round";
                                ctx.lineJoin = "round";
                                for (let i = firstBand; i <= lastBand; i++) {
                                    const band = sliders.itemAt(i);
                                    if (!band) break;
                                    const knob = band.knobItem;
                                    const point = knob.mapToItem(presetLightning, knob.width / 2, knob.height / 2);
                                    points.push(point);

                                    const pulse = pulseAt(i);
                                    if (pulse >= 1) continue;
                                    const glow = 2 ** (-9 * pulse) * fade;
                                    const radius = 6 + 14 * (1 - glow);
                                    const rail = band.railItem;
                                    const top = rail.mapToItem(presetLightning, 0, 0).y - radius;
                                    const bottom = top + rail.height + 2 * radius;
                                    ctx.beginPath();
                                    ctx.moveTo(point.x - radius, top + radius);
                                    ctx.arc(point.x, top + radius, radius, Math.PI, 2 * Math.PI);
                                    ctx.lineTo(point.x + radius, bottom - radius);
                                    ctx.arc(point.x, bottom - radius, radius, 0, Math.PI);
                                    ctx.closePath();
                                    ctx.strokeStyle = accent;
                                    ctx.lineWidth = 12 + 4 * glow;
                                    ctx.globalAlpha = 0.13 * glow;
                                    ctx.stroke();
                                    ctx.lineWidth = 4 + 3 * glow;
                                    ctx.globalAlpha = 0.14 * glow;
                                    ctx.stroke();
                                }

                                const tip = Math.min(reach - firstBand, points.length - 1);
                                if (tip <= 0) return;
                                const phase = elapsed * 0.014;
                                for (let strandIndex = 0; strandIndex < strands.length; strandIndex++) {
                                    const strand = strands[strandIndex];
                                    ctx.beginPath();
                                    ctx.moveTo(points[0].x, points[0].y);
                                    for (let i = 0; i < tip; i++) {
                                        const a = points[i], b = points[i + 1];
                                        const end = Math.min(1, tip - i);
                                        for (let step = 1; step <= 8; step++) {
                                            const t = Math.min(end, step / 8);
                                            const angle = phase + i * 1.9 + strandIndex * 1.7;
                                            const bend = Math.sin(Math.PI * t) * strand.amplitude * fade;
                                            const x = a.x + (b.x - a.x) * t + bend * 0.42 * Math.cos(angle * 0.73 + step * 2.4);
                                            const y = a.y + (b.y - a.y) * t + bend * (Math.sin(angle + step * 2.8) + 0.48 * Math.cos(angle * 0.63 - step * 1.6));
                                            ctx.lineTo(x, y);
                                            if (t === end) break;
                                        }
                                    }
                                    ctx.strokeStyle = strand.color;
                                    ctx.lineWidth = strand.width;
                                    ctx.globalAlpha = strand.opacity * fade;
                                    ctx.stroke();
                                }

                                // Draw the handle-to-handle line over the jagged glow.
                                ctx.beginPath();
                                ctx.moveTo(points[0].x, points[0].y);
                                const last = Math.ceil(tip);
                                for (let i = 1; i < last; i++) ctx.lineTo(points[i].x, points[i].y);
                                const a = points[last - 1], b = points[last];
                                const fraction = tip - (last - 1);
                                ctx.lineTo(a.x + (b.x - a.x) * fraction, a.y + (b.y - a.y) * fraction);
                                ctx.globalAlpha = fade;
                                ctx.strokeStyle = core;
                                ctx.lineWidth = 3.5;
                                ctx.stroke();
                                ctx.globalAlpha = 1;
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
                            text: qsTr("Preset: %1").arg(root.equalizer.activePreset)
                            color: Colours.palette.m3onSurface
                        }
                        Item { Layout.fillWidth: true }
                        TextButton {
                            text: qsTr("Reset to flat")
                            disabled: !root.equalizer.ready
                            onClicked: root.selectPreset(0)
                        }
                        TextButton {
                            text: qsTr("Reconnect")
                            disabled: root.equalizer.busy
                            onClicked: root.equalizer.refresh()
                        }
                    }
                    Flow {
                        Layout.fillWidth: true
                        Layout.preferredHeight: implicitHeight
                        spacing: 5
                        Repeater {
                            model: root.equalizer.presetNames
                            delegate: TextButton {
                                required property int index
                                required property string modelData
                                text: modelData
                                type: TextButton.Tonal
                                checked: root.equalizer.activePreset === modelData
                                disabled: !root.equalizer.ready
                                horizontalPadding: Math.max(Tokens.padding.small, Tokens.padding.medium - 3)
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
