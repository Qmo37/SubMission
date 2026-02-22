import React, { useRef, useEffect, useCallback } from 'react';

function VideoPlayer({ videoPath, currentTime, onTimeUpdate, onDurationChange, overlayTexts = [] }) {
    const videoRef = useRef(null);
    const isSeeking = useRef(false);

    useEffect(() => {
        const video = videoRef.current;
        if (!video) return;

        const handleTimeUpdate = () => {
            if (!isSeeking.current) {
                onTimeUpdate(video.currentTime);
            }
        };
        const handleMetadata = () => {
            onDurationChange(video.duration);
        };

        video.addEventListener('timeupdate', handleTimeUpdate);
        video.addEventListener('loadedmetadata', handleMetadata);
        return () => {
            video.removeEventListener('timeupdate', handleTimeUpdate);
            video.removeEventListener('loadedmetadata', handleMetadata);
        };
    }, [onTimeUpdate, onDurationChange]);

    // Sync video position when currentTime changes externally (timeline scrub)
    const seekToTime = useCallback((time) => {
        const video = videoRef.current;
        if (!video || !video.duration) return;
        if (Math.abs(video.currentTime - time) > 0.5) {
            isSeeking.current = true;
            video.currentTime = time;
            setTimeout(() => { isSeeking.current = false; }, 100);
        }
    }, []);

    // Expose seekToTime via parent calling it through ref-like pattern
    useEffect(() => {
        if (videoRef.current && videoRef.current._lastExternalTime !== currentTime) {
            videoRef.current._lastExternalTime = currentTime;
        }
    }, [currentTime]);

    const videoSrc = videoPath
        ? `/api/video?path=${encodeURIComponent(videoPath)}`
        : undefined;

    return (
        <div className="video-player">
            <div className="video-wrapper">
                {videoSrc ? (
                    <video
                        ref={videoRef}
                        src={videoSrc}
                        controls
                        style={{ width: '100%', height: '100%', objectFit: 'contain', background: '#000' }}
                    />
                ) : (
                    <div className="video-placeholder">
                        <span>No video loaded</span>
                    </div>
                )}

                {overlayTexts.map((text, idx) => (
                    <div key={idx} className="subtitle-overlay" style={{ bottom: `${20 + idx * 45}px` }}>
                        <span>{text}</span>
                    </div>
                ))}
            </div>
        </div>
    );
}

export default VideoPlayer;
