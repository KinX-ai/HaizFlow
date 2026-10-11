import QtQuick
import "."

IconButton {
    id: root
    property real speed: 1.0
    implicitWidth: 42
    toolTipText: qsTr("Tốc độ phát %1x").arg(speed)
    contentItem: Text {
        text: root.speed + "x"
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        color: root.enabled ? Theme.textMuted : Theme.textSubtle
        font.pixelSize: Theme.caption
        font.family: Theme.fontFamily
        font.weight: Font.DemiBold
        Accessible.ignored: true
    }
}
