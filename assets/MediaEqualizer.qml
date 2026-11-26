pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import Caelestia.Config
import qs.components
import qs.components.controls
import qs.services
import "equalizer"
import "media"

Item {
    id: root

    required property ScreenState screenState
    readonly property bool expanded: disclosure.checked
    readonly property int screenHeight: screenState.modelData?.height ?? 0
    readonly property int equalizerHeight: 480

    implicitWidth: media.implicitWidth
    implicitHeight: Math.min(body.implicitHeight, screenHeight > 0 ? Math.max(1, screenHeight - 160) : body.implicitHeight)

    Flickable {
        id: viewport

        anchors.fill: parent
        contentWidth: width
        contentHeight: body.implicitHeight
        flickableDirection: Flickable.VerticalFlick
        boundsBehavior: Flickable.StopAtBounds
        interactive: contentHeight > height
        clip: true

        Controls.ScrollBar.vertical: StyledScrollBar {
            flickable: viewport
            policy: viewport.interactive ? Controls.ScrollBar.AlwaysOn : Controls.ScrollBar.AlwaysOff
        }

        Loader {
            id: mediaBackdrop

            // Keep the full field in place while the visible area expands and collapses.
            width: viewport.width
            height: media.height + disclosure.height + panel.y + root.equalizerHeight
            z: -1
            active: width > 0
            asynchronous: true

            sourceComponent: BackgroundShapes {
                width: mediaBackdrop.width
                height: mediaBackdrop.height
                count: 28
                opacity: 0.65
            }
        }

        Column {
            id: body

            width: viewport.width

            Media {
                id: media

                width: parent.width
                height: implicitHeight
                screenState: root.screenState
                showMediaBackground: false
            }

            Controls.AbstractButton {
                id: disclosure

                width: parent.width
                checkable: true
                hoverEnabled: true
                text: qsTr("Equalizer")
                leftPadding: Tokens.padding.large
                rightPadding: Tokens.padding.large
                topPadding: Tokens.padding.medium
                bottomPadding: Tokens.padding.medium
                implicitHeight: contentItem.implicitHeight + topPadding + bottomPadding
                Accessible.name: text
                Accessible.description: checked ? qsTr("Collapse equalizer controls") : qsTr("Expand equalizer controls")

                background: StyledRect {
                    radius: Tokens.rounding.large
                    color: disclosure.down || disclosure.hovered ? Qt.alpha(Colours.palette.m3surfaceContainerHigh, 0.45)
                        : Qt.alpha(Colours.palette.m3surfaceContainer, 0.22)
                    border.width: disclosure.visualFocus ? 1 : 0
                    border.color: Colours.palette.m3primary
                }

                contentItem: RowLayout {
                    spacing: Tokens.spacing.medium

                    MaterialIcon {
                        text: "equalizer"
                        color: Colours.palette.m3primary
                    }

                    StyledText {
                        text: disclosure.text
                        font: Tokens.font.body.builders.large.weight(Font.DemiBold).build()
                    }

                    Item { Layout.fillWidth: true }

                    StyledText {
                        visible: EqualizerState.ready
                        text: EqualizerState.bypass || EqualizerState.globalBypass ? qsTr("Off") : EqualizerState.activePreset
                        color: Colours.palette.m3onSurfaceVariant
                    }

                    MaterialIcon {
                        text: "expand_more"
                        rotation: disclosure.checked ? 180 : 0
                        color: Colours.palette.m3onSurfaceVariant
                        Behavior on rotation { Anim {} }
                    }
                }
            }

            Item {
                id: reveal

                width: parent.width
                height: root.expanded && panel.item ? panel.item.implicitHeight + panel.y : 0
                clip: true

                Behavior on height { Anim {} }

                Loader {
                    id: panel

                    y: Tokens.spacing.small
                    width: parent.width
                    asynchronous: true
                    active: root.expanded || reveal.height > 0

                    sourceComponent: EqualizerTab {
                        implicitHeight: root.equalizerHeight
                        surfaceColor: Qt.alpha(Colours.palette.m3surfaceContainer, 0.18)
                        controlsActive: visible && root.expanded && root.screenState.dashboard
                    }
                }
            }
        }
    }
}
