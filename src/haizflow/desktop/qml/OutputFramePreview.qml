pragma ComponentBehavior: Bound
import QtQuick
import QtMultimedia
import QtQuick.Effects

Item {
    id: root
    property string outputFormat: "keep_ratio"
    property url thumbnailSource: ""
    property bool showThumbnail: false
    property string thumbnailOutputFormat: outputFormat
    readonly property bool thumbnailVisible: showThumbnail && thumbnail.status === Image.Ready
    readonly property string displayFormat: thumbnailVisible ? thumbnailOutputFormat : outputFormat
    readonly property Item frameSource: thumbnailVisible ? thumbnail : video
    readonly property rect frameRect: thumbnailVisible
        ? Qt.rect((thumbnail.width - thumbnail.paintedWidth) / 2,
            (thumbnail.height - thumbnail.paintedHeight) / 2, thumbnail.paintedWidth, thumbnail.paintedHeight)
        : video.contentRect
    property alias videoOutput: video
    property alias videoSink: video.videoSink
    property alias endOfStreamPolicy: video.endOfStreamPolicy
    readonly property bool portrait: displayFormat === "blur_background_9_16"
        || displayFormat === "tiktok_9_16_crop"
    readonly property rect contentRect: portrait
        ? Qt.rect(canvas.x, canvas.y, canvas.width, canvas.height) : frameRect
    function clearOutput() { video.clearOutput(); }

    Item {
        id: canvas
        width: root.portrait ? Math.min(root.width, root.height * 9 / 16) : root.width
        height: root.portrait ? width * 16 / 9 : root.height
        anchors.centerIn: parent
        clip: root.portrait

        Loader {
            anchors.fill: parent
            active: root.visible && root.displayFormat === "blur_background_9_16"
                && root.frameRect.width > 0 && root.frameRect.height > 0
            sourceComponent: Component {
                Item {
                    id: background
                    readonly property real ratio: root.frameRect.width / Math.max(1, root.frameRect.height)
                    readonly property real smallWidth: Math.min(270, 480 * ratio)
                    readonly property real smallHeight: smallWidth / ratio
                    ShaderEffectSource {
                        id: capture
                        sourceItem: root.frameSource
                        sourceRect: root.frameRect
                        textureSize: Qt.size(Math.ceil(background.smallWidth), Math.ceil(background.smallHeight))
                        width: background.smallWidth
                        height: background.smallHeight
                        visible: false
                        live: false
                        Component.onCompleted: scheduleUpdate()
                        onSourceRectChanged: scheduleUpdate()
                        onTextureSizeChanged: scheduleUpdate()
                        onSourceItemChanged: scheduleUpdate()
                    }
                    Connections {
                        target: video.videoSink
                        function onVideoFrameChanged() { capture.scheduleUpdate(); }
                    }
                    MultiEffect {
                        source: capture
                        width: background.smallWidth
                        height: background.smallHeight
                        anchors.centerIn: parent
                        scale: Math.max(background.width / width, background.height / height)
                        blurEnabled: true
                        blur: 1
                        blurMax: 16
                        autoPaddingEnabled: false
                    }
                }
            }
        }
        VideoOutput {
            id: video
            objectName: "outputFrameVideo"
            anchors.fill: parent
            endOfStreamPolicy: VideoOutput.KeepLastFrame
            fillMode: root.outputFormat === "tiktok_9_16_crop"
                ? VideoOutput.PreserveAspectCrop : VideoOutput.PreserveAspectFit
        }
        Image {
            id: thumbnail
            objectName: "outputFrameThumbnail"
            anchors.fill: parent
            source: root.showThumbnail ? root.thumbnailSource : ""
            sourceSize.width: 960
            sourceSize.height: 540
            fillMode: root.thumbnailOutputFormat === "tiktok_9_16_crop"
                ? Image.PreserveAspectCrop : Image.PreserveAspectFit
            asynchronous: true
            visible: root.thumbnailVisible
        }
    }
}
