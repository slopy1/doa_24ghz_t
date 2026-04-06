#!/bin/bash
# record_experiment.sh
# Records webcam video and audio for thesis experiments.
# Usage: ./record_experiment.sh [-p] [device]

OUTPUT_DIR="./recordings"
mkdir -p "$OUTPUT_DIR"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H_%M_%S")
FILENAME="$OUTPUT_DIR/experiment_$TIMESTAMP.mkv"

# Check for preview flag
PREVIEW_MODE=false
if [[ "$1" == "-p" || "$1" == "--preview" ]]; then
    PREVIEW_MODE=true
    shift # Remove flag from arguments
fi

# Default to /dev/video0 (or first remaining arg)
VIDEO_DEVICE="${1:-/dev/video0}"

# List devices for user info if not found or just to show
if [ ! -e "$VIDEO_DEVICE" ]; then
    echo "Error: Device $VIDEO_DEVICE not found."
    echo "Available video devices:"
    ls -l /dev/video*
    exit 1
fi

echo "========================================================"
echo "Experiment Recording Setup"
echo "Video Device: $VIDEO_DEVICE"
echo "Output File : $FILENAME"
echo "========================================================"

if [ "$PREVIEW_MODE" = true ]; then
    echo "Starting PREVIEW mode..."
    echo "Close the preview window (or press 'q' inside it) to START recording."
    echo "Press Ctrl+C in terminal to abort."
    
    # Run ffplay for preview. 
    # -window_title sets the window name
    # -noborder removes border for cleaner look (optional, maybe keep for moving)
    # -x 640 -y 360 scales preview window to be smaller/manageable
    ffplay -f v4l2 -framerate 30 -video_size 1280x720 -i "$VIDEO_DEVICE" \
           -window_title "Camera Preview - Close to Start Recording" \
           -x 640 -y 360 -autoexit >/dev/null 2>&1
           
    echo "--------------------------------------------------------"
    echo "Preview closed. Starting recording in 3 seconds..."
    echo "Press Ctrl+C NOW if you do NOT want to record."
    sleep 3
fi

echo "Starting recording..."
echo "SYNC_MARKER_START" 
echo "Stop        : Press 'q' or Ctrl+C"

# ffmpeg arguments explained:
# -y : Overwrite output file if exists
# -f v4l2 : Video4Linux2 input
# -framerate 30 : Target 30 fps
# -video_size 1280x720 : Standard HD resolution
# -i ... : Input device
# -f alsa -i default : Use default audio input
# -c:v libx264 : H.264 video codec
# -preset ultrafast : Minimal CPU usage
# -crf 23 : Quality factor
# -c:a aac : AAC audio codec

ffmpeg \
    -y \
    -f v4l2 -framerate 30 -video_size 1280x720 -i "$VIDEO_DEVICE" \
    -f alsa -i default \
    -c:v libx264 -preset ultrafast -crf 23 \
    -c:a aac \
    "$FILENAME"

echo "Recording saved to $FILENAME"
