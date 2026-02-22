import React, { useRef, useState, useEffect } from 'react';

function Timeline({ currentTime, duration, tracks = [], overlayTracks = [], onTrackToggle, onTimeScrub, onBlockDrag, onBlockEdit, whisperDisplayMode, onWhisperModeToggle }) {
    const timelineRef = useRef(null);
    const [scale, setScale] = useState(50);
    const [draggingBlock, setDraggingBlock] = useState(null);

    const TRACK_HEIGHT = 55;
    const HEADER_HEIGHT = 30;
    const TRACK_GAP = 6;
    const TIMELINE_PADDING = 20;
    const LABEL_WIDTH = 120;

    useEffect(() => {
        const handleMouseMove = (e) => {
            if (!draggingBlock || !timelineRef.current) return;
            const rect = timelineRef.current.getBoundingClientRect();
            const scrollLeft = timelineRef.current.scrollLeft;
            const mouseX = e.clientX - rect.left + scrollLeft - TIMELINE_PADDING - LABEL_WIDTH;
            let newStart = mouseX / scale;
            const blockDuration = draggingBlock.end - draggingBlock.start;
            if (newStart < 0) newStart = 0;
            onBlockDrag(draggingBlock.id, newStart, newStart + blockDuration);
        };

        const handleMouseUp = () => {
            setDraggingBlock(null);
        };

        if (draggingBlock) {
            window.addEventListener('mousemove', handleMouseMove);
            window.addEventListener('mouseup', handleMouseUp);
        }
        return () => {
            window.removeEventListener('mousemove', handleMouseMove);
            window.removeEventListener('mouseup', handleMouseUp);
        };
    }, [draggingBlock, scale, onBlockDrag]);

    const handleTimelineClick = (e) => {
        if (draggingBlock || !timelineRef.current) return;
        if (e.target.closest('.timeline-block')) return;
        const rect = timelineRef.current.getBoundingClientRect();
        const scrollLeft = timelineRef.current.scrollLeft;
        const clickX = e.clientX - rect.left + scrollLeft - TIMELINE_PADDING - LABEL_WIDTH;
        const newTime = Math.max(0, clickX / scale);
        onTimeScrub(newTime);
    };

    const handleBlockMouseDown = (e, block, editable) => {
        if (!editable) return;
        e.stopPropagation();
        setDraggingBlock(block);
    };

    const handleBlockDoubleClick = (e, trackId, block) => {
        e.stopPropagation();
        onBlockEdit(trackId, block);
    };

    const totalWidth = duration * scale + TIMELINE_PADDING * 2 + LABEL_WIDTH;
    const cursorLeft = (currentTime * scale) + TIMELINE_PADDING + LABEL_WIDTH;

    const renderBlock = (block, track) => {
        const isAnchor = track.id === 'anchors';
        const isDragging = draggingBlock?.id === block.id;

        const bgColor = isAnchor
            ? `rgba(34, 197, 94, ${0.2 + (block.confidence || 0) * 0.5})`
            : `var(${track.color})`;
        const borderColor = isAnchor
            ? '#22c55e'
            : `var(${track.borderColor})`;

        let displayStr = '';
        if (isAnchor) {
            displayStr = block.offset != null ? `${block.offset > 0 ? '+' : ''}${block.offset.toFixed(1)}s` : '';
        } else if (track.id === 'whisper') {
            displayStr = whisperDisplayMode === 'original' ? (block.original_text || block.text) : block.text;
        } else {
            displayStr = block.text;
        }

        return (
            <div
                key={block.id}
                className="timeline-block"
                title={isAnchor
                    ? `offset: ${block.offset?.toFixed(2)}s, confidence: ${((block.confidence || 0) * 100).toFixed(0)}%`
                    : `${block.start?.toFixed(2)}s - ${block.end?.toFixed(2)}s`
                }
                onMouseDown={track.editable ? (e) => handleBlockMouseDown(e, block, true) : undefined}
                onDoubleClick={(e) => handleBlockDoubleClick(e, track.id, block)}
                style={{
                    position: 'absolute',
                    left: `${block.start * scale + TIMELINE_PADDING + LABEL_WIDTH}px`,
                    width: `${Math.max((block.end - block.start) * scale, 2)}px`,
                    height: `${TRACK_HEIGHT - 14}px`,
                    background: bgColor,
                    border: `1px solid ${borderColor}`,
                    borderRadius: 'var(--radius-sm)',
                    color: 'white',
                    fontSize: '0.7rem',
                    padding: '3px 4px',
                    overflow: 'hidden',
                    whiteSpace: 'nowrap',
                    textOverflow: 'ellipsis',
                    top: '14px',
                    cursor: track.editable ? (isDragging ? 'grabbing' : 'grab') : 'pointer',
                    boxShadow: isDragging ? 'var(--shadow-glow)' : 'none',
                    zIndex: isDragging ? 10 : 1,
                }}
            >
                {displayStr}
            </div>
        );
    };

    return (
        <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
            <div style={{ padding: '8px 12px', borderBottom: '1px solid var(--border-subtle)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <h3 style={{ margin: 0, fontSize: '0.95rem' }}>Timeline</h3>
                <div>
                    <button onClick={() => setScale(s => Math.max(10, s - 10))} style={{ padding: '3px 7px', marginRight: '6px', fontSize: '0.8rem' }}>-</button>
                    <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Zoom</span>
                    <button onClick={() => setScale(s => Math.min(200, s + 10))} style={{ padding: '3px 7px', marginLeft: '6px', fontSize: '0.8rem' }}>+</button>
                </div>
            </div>

            <div
                ref={timelineRef}
                style={{
                    flex: 1,
                    overflowX: 'auto',
                    overflowY: 'auto',
                    position: 'relative',
                    background: 'rgba(0,0,0,0.2)',
                    cursor: 'text'
                }}
                onClick={handleTimelineClick}
            >
                <div style={{
                    width: `${totalWidth}px`,
                    height: `${HEADER_HEIGHT + tracks.length * (TRACK_HEIGHT + TRACK_GAP) + TRACK_GAP}px`,
                    position: 'relative',
                    minHeight: '100%',
                }}>
                    {/* Time ticks header */}
                    <div style={{ height: `${HEADER_HEIGHT}px`, borderBottom: '1px solid var(--border-subtle)', position: 'relative' }}>
                        {Array.from({ length: Math.ceil(duration) }).map((_, i) => (
                            i % 5 === 0 && (
                                <div key={i} style={{
                                    position: 'absolute',
                                    left: `${i * scale + TIMELINE_PADDING + LABEL_WIDTH}px`,
                                    top: '10px',
                                    fontSize: '0.65rem',
                                    color: 'var(--text-muted)',
                                }}>
                                    {i}s
                                </div>
                            )
                        ))}
                    </div>

                    {/* Dynamic tracks */}
                    {tracks.map((track, trackIdx) => {
                        const trackTop = HEADER_HEIGHT + trackIdx * (TRACK_HEIGHT + TRACK_GAP) + TRACK_GAP;
                        const isLast = trackIdx === tracks.length - 1;

                        return (
                            <div
                                key={track.id}
                                style={{
                                    position: 'absolute',
                                    top: `${trackTop}px`,
                                    left: 0,
                                    width: '100%',
                                    height: `${TRACK_HEIGHT}px`,
                                    borderBottom: isLast ? 'none' : '1px dashed var(--border-subtle)',
                                }}
                            >
                                {/* Track label with checkbox */}
                                <div className="track-checkbox" style={{ top: '2px', position: 'sticky', zIndex: 100 }}>
                                    <input
                                        title="Display as overlay on Video Player (Max 2)"
                                        type="checkbox"
                                        checked={overlayTracks.includes(track.id)}
                                        onChange={() => onTrackToggle(track.id)}
                                        disabled={!overlayTracks.includes(track.id) && overlayTracks.length >= 2}
                                    />
                                    <span>{track.label}</span>
                                    {track.id === 'whisper' && (
                                        <button
                                            onClick={(e) => { e.stopPropagation(); onWhisperModeToggle(); }}
                                            style={{ marginLeft: '6px', padding: '1px 4px', fontSize: '0.6rem', height: 'auto' }}
                                        >
                                            {whisperDisplayMode === 'translated' ? 'Trans' : 'Orig'}
                                        </button>
                                    )}
                                </div>

                                {/* Blocks */}
                                {(track.blocks || []).map(block => renderBlock(block, track))}
                            </div>
                        );
                    })}

                    {/* Cursor */}
                    <div
                        style={{
                            position: 'absolute',
                            top: 0,
                            bottom: 0,
                            left: `${cursorLeft}px`,
                            width: '2px',
                            background: '#ef4444',
                            zIndex: 20,
                            pointerEvents: 'none',
                            transform: 'translateX(-50%)',
                        }}
                    >
                        <div style={{
                            width: '0',
                            height: '0',
                            borderLeft: '6px solid transparent',
                            borderRight: '6px solid transparent',
                            borderTop: '8px solid #ef4444',
                            position: 'absolute',
                            top: 0,
                            left: '-5px',
                        }} />
                    </div>
                </div>
            </div>
        </div>
    );
}

export default Timeline;
