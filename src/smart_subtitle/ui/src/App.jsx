import React, { useState, useEffect, useCallback, useRef } from 'react';
import Timeline from './components/Timeline';
import Sidebar from './components/Sidebar';
import VideoPlayer from './components/VideoPlayer';
import FilePicker from './components/FilePicker';
import './index.css';

function App() {
    const [currentTime, setCurrentTime] = useState(0);
    const [duration, setDuration] = useState(120);

    // Track data
    const [whisperBlocks, setWhisperBlocks] = useState([]);
    const [subtitleBlocks, setSubtitleBlocks] = useState({}); // { path: blocks[] }
    const [anchorBlocks, setAnchorBlocks] = useState([]);
    const [stageData, setStageData] = useState({}); // { "5": { output_blocks, label }, ... }
    const [selectedStage, setSelectedStage] = useState(null);
    const [latestStage, setLatestStage] = useState(0);

    // Overlay tracks
    const [overlayTracks, setOverlayTracks] = useState(['output']);
    const [whisperDisplayMode, setWhisperDisplayMode] = useState('translated');

    // Undo/Redo history for Output blocks
    const [history, setHistory] = useState([]);
    const [historyIndex, setHistoryIndex] = useState(-1);

    const pushStageDataHistory = (newData) => {
        const nextHist = history.slice(0, historyIndex + 1);
        nextHist.push(newData);
        setHistory(nextHist);
        setHistoryIndex(nextHist.length - 1);
        setStageData(newData);
    };

    const handleUndo = () => {
        if (historyIndex > 0) {
            setHistoryIndex(historyIndex - 1);
            setStageData(history[historyIndex - 1]);
        }
    };

    const handleRedo = () => {
        if (historyIndex < history.length - 1) {
            setHistoryIndex(historyIndex + 1);
            setStageData(history[historyIndex + 1]);
        }
    };

    // Config
    const [config, setConfig] = useState(null);

    // File paths
    const [videoPath, setVideoPath] = useState('');
    const [subtitlePaths, setSubtitlePaths] = useState(['', '']);

    // Job state
    const [loading, setLoading] = useState(false);
    const [stage, setStage] = useState('');
    const [detail, setDetail] = useState('');
    const [progress, setProgress] = useState(null);
    const [error, setError] = useState(null);
    const [jobId, setJobId] = useState(null);

    // File picker
    const [pickerOpen, setPickerOpen] = useState(false);
    const [pickerFilter, setPickerFilter] = useState(null);
    const [pickerTarget, setPickerTarget] = useState(null); // 'video' | 'sub-0' | 'sub-1'
    const [pickerTitle, setPickerTitle] = useState('');

    const pollRef = useRef(null);

    useEffect(() => {
        fetch('/api/config')
            .then(r => r.json())
            .then(setConfig)
            .catch(e => console.error('Failed to load config:', e));

        return () => {
            if (pollRef.current) clearInterval(pollRef.current);
        };
    }, []);

    const handleConfigChange = useCallback((section, key, value) => {
        setConfig(prev => ({
            ...prev,
            [section]: { ...prev[section], [key]: value }
        }));

        const body = { [section]: { [key]: value } };
        fetch('/api/config', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        }).catch(e => console.error('Failed to save config:', e));
    }, []);

    const pollJob = useCallback((jid) => {
        if (pollRef.current) clearInterval(pollRef.current);

        pollRef.current = setInterval(async () => {
            try {
                const resp = await fetch(`/api/align/status/${jid}`);
                if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
                const job = await resp.json();

                setStage(job.stage || '');
                setDetail(job.detail || '');
                setProgress(job.progress || null);

                // Progressive update: check if new stage data arrived
                if (job.latest_stage > latestStage) {
                    setLatestStage(job.latest_stage);
                }

                if (job.result) {
                    const data = job.result;
                    setDuration(data.duration || 120);
                    setWhisperBlocks(data.whisper_blocks || []);
                    setSubtitleBlocks(data.subtitle_blocks || {});
                    setAnchorBlocks(data.anchor_blocks || []);

                    if (data.stages) {
                        setStageData(data.stages);
                        setHistory(prev => {
                            if (prev.length === 0) return [data.stages];
                            return prev;
                        });
                        setHistoryIndex(prev => prev === -1 ? 0 : prev);
                        // Auto-select the latest stage
                        const stageNums = Object.keys(data.stages).map(Number).sort((a, b) => b - a);
                        if (stageNums.length > 0) {
                            setSelectedStage(prev => prev || String(stageNums[0]));
                        }
                    }
                }

                if (job.status === 'complete' && job.latest_stage >= 7) {
                    clearInterval(pollRef.current);
                    pollRef.current = null;
                    setLoading(false);
                    setStage('Done');
                } else if (job.status === 'complete' && !loading) {
                    // Phase 1 complete, keep polling for phase 2
                    // Already showing data, just keep polling
                } else if (job.status === 'error') {
                    clearInterval(pollRef.current);
                    pollRef.current = null;
                    setError(job.error || 'Unknown error');
                    setLoading(false);
                }
            } catch (e) {
                console.warn('Poll error:', e);
            }
        }, 2000);
    }, [latestStage, loading]);

    const handleRunAlignment = useCallback(async () => {
        if (!videoPath) {
            setError('Please enter a video file path.');
            return;
        }
        const validSubs = subtitlePaths.filter(p => p.trim());
        if (validSubs.length === 0) {
            setError('Please enter at least one subtitle file path.');
            return;
        }

        setLoading(true);
        setError(null);
        setStage('Submitting job...');
        setStageData({});
        setHistory([]);
        setHistoryIndex(-1);
        setSelectedStage(null);
        setLatestStage(0);

        try {
            const resp = await fetch('/api/align/anchors', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    video_path: videoPath,
                    subtitle_paths: validSubs,
                }),
            });

            if (!resp.ok) {
                const data = await resp.json();
                throw new Error(data.detail || `HTTP ${resp.status}`);
            }

            const { job_id } = await resp.json();
            setJobId(job_id);
            setStage('Job started, waiting for progress...');
            pollJob(job_id);
        } catch (e) {
            setError(e.message);
            setLoading(false);
            setStage('');
        }
    }, [videoPath, subtitlePaths, pollJob]);

    const handleExport = useCallback(() => {
        if (!jobId) return;
        window.open(`/api/export/${jobId}`, '_blank');
    }, [jobId]);

    const handleTimeScrub = (time) => {
        setCurrentTime(time);
    };

    const handleBlockDrag = (id, newStart, newEnd) => {
        let updated = false;
        const newStageData = { ...stageData };
        for (const key of Object.keys(newStageData)) {
            const stage = newStageData[key];
            if (stage.output_blocks) {
                const idx = stage.output_blocks.findIndex(b => b.id === id);
                if (idx >= 0) {
                    newStageData[key] = {
                        ...stage,
                        output_blocks: stage.output_blocks.map(b =>
                            b.id === id ? { ...b, start: newStart, end: newEnd } : b
                        ),
                    };
                    updated = true;
                }
            }
        }
        if (updated) pushStageDataHistory(newStageData);
    };

    const handleBlockEdit = (trackId, block) => {
        if (trackId !== 'output') return;
        const newText = window.prompt('Edit subtitle text:', block.text);
        if (newText !== null && newText !== block.text) {
            let updated = false;
            const newStageData = { ...stageData };
            for (const key of Object.keys(newStageData)) {
                const stage = newStageData[key];
                if (stage.output_blocks) {
                    const idx = stage.output_blocks.findIndex(b => b.id === block.id);
                    if (idx >= 0) {
                        newStageData[key] = {
                            ...stage,
                            output_blocks: stage.output_blocks.map(b =>
                                b.id === block.id ? { ...b, text: newText } : b
                            ),
                        };
                        updated = true;
                    }
                }
            }
            if (updated) pushStageDataHistory(newStageData);
        }
    };

    const handleSubtitlePathChange = (index, value) => {
        setSubtitlePaths(prev => prev.map((p, i) => i === index ? value : p));
    };

    const openFilePicker = (target, filter, title) => {
        setPickerTarget(target);
        setPickerFilter(filter);
        setPickerTitle(title);
        setPickerOpen(true);
    };

    const handleFileSelect = (path) => {
        if (pickerTarget === 'video') {
            setVideoPath(path);
        } else if (pickerTarget?.startsWith('sub-')) {
            const idx = parseInt(pickerTarget.split('-')[1]);
            handleSubtitlePathChange(idx, path);
        }
    };

    // Build tracks for Timeline
    const subPaths = Object.keys(subtitleBlocks);
    const outputBlocks = selectedStage && stageData[selectedStage]
        ? stageData[selectedStage].output_blocks || []
        : [];

    const tracks = [];
    tracks.push({
        id: 'whisper', label: 'Whisper', blocks: whisperBlocks,
        color: '--track-whisper', borderColor: '--track-whisper-border', editable: false,
    });
    if (subPaths.length > 0) {
        tracks.push({
            id: 'sub1', label: subPaths[0]?.split('/').pop() || 'Subtitle 1',
            blocks: subtitleBlocks[subPaths[0]] || [],
            color: '--track-sub', borderColor: '--track-sub-border', editable: false,
        });
    }
    if (subPaths.length > 1) {
        tracks.push({
            id: 'sub2', label: subPaths[1]?.split('/').pop() || 'Subtitle 2',
            blocks: subtitleBlocks[subPaths[1]] || [],
            color: '--track-sub2', borderColor: '--track-sub2-border', editable: false,
        });
    }
    tracks.push({
        id: 'anchors', label: 'Anchors', blocks: anchorBlocks,
        color: '--track-anchor', borderColor: '--track-anchor-border', editable: false,
    });
    tracks.push({
        id: 'output', label: `Output (Stage ${selectedStage || '?'})`, blocks: outputBlocks,
        color: '--track-output', borderColor: '--track-output-border', editable: true,
    });

    // Determine overlay text at current time
    const getOverlayTexts = () => {
        const texts = [];
        for (const trk of overlayTracks) {
            let blocks = [];
            if (trk === 'output') blocks = outputBlocks;
            else if (trk === 'whisper') blocks = whisperBlocks;
            else if (trk === 'sub1') blocks = subtitleBlocks[subPaths[0]] || [];
            else if (trk === 'sub2') blocks = subtitleBlocks[subPaths[1]] || [];

            const active = blocks.find(b => b.start <= currentTime && b.end >= currentTime);
            if (active) {
                if (trk === 'whisper' && whisperDisplayMode === 'original') {
                    texts.push(active.original_text || active.text);
                } else {
                    texts.push(active.text);
                }
            }
        }
        return texts;
    };

    return (
        <div className="app-container">
            {/* File Bar */}
            <div className="filebar-area glass-panel">
                <div className="filebar-group">
                    <label>Video:</label>
                    <input
                        type="text"
                        placeholder="/path/to/video.mp4"
                        value={videoPath}
                        onChange={e => setVideoPath(e.target.value)}
                    />
                    <button className="browse-btn" onClick={() => openFilePicker('video', 'video', 'Select Video')}>
                        Browse
                    </button>
                </div>

                <div className="filebar-group">
                    <label>Sub 1:</label>
                    <input
                        type="text"
                        placeholder="/path/to/subtitle_1.srt"
                        value={subtitlePaths[0]}
                        onChange={e => handleSubtitlePathChange(0, e.target.value)}
                    />
                    <button className="browse-btn" onClick={() => openFilePicker('sub-0', 'subtitle', 'Select Subtitle 1')}>
                        Browse
                    </button>
                </div>

                <div className="filebar-group">
                    <label>Sub 2:</label>
                    <input
                        type="text"
                        placeholder="/path/to/subtitle_2.srt (optional)"
                        value={subtitlePaths[1]}
                        onChange={e => handleSubtitlePathChange(1, e.target.value)}
                    />
                    <button className="browse-btn" onClick={() => openFilePicker('sub-1', 'subtitle', 'Select Subtitle 2')}>
                        Browse
                    </button>
                </div>
            </div>

            {/* Video Player */}
            <div className="player-area glass-panel">
                {loading && !whisperBlocks.length ? (
                    <div className="progress-section" style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                        <div style={{ maxWidth: '500px', width: '100%' }}>
                            <h2>Running Pipeline...</h2>
                            <p style={{ marginTop: '10px', color: 'var(--accent-blue)', fontWeight: 500 }}>{stage}</p>
                            {progress && progress.total > 0 && (
                                <div>
                                    <div className="progress-bar-bg">
                                        <div className="progress-bar-fill" style={{ width: `${(progress.current / progress.total) * 100}%` }} />
                                    </div>
                                    <p style={{ marginTop: '6px', fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                                        {progress.current} / {progress.total} {progress.unit}
                                    </p>
                                </div>
                            )}
                            {detail && (
                                <p style={{ marginTop: '8px', fontSize: '0.8rem', color: 'var(--text-muted)', fontFamily: 'monospace' }}>
                                    {detail}
                                </p>
                            )}
                        </div>
                    </div>
                ) : error && !whisperBlocks.length ? (
                    <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#ef4444' }}>
                        <div style={{ textAlign: 'center' }}>
                            <h3>Error</h3>
                            <p style={{ marginTop: '8px' }}>{error}</p>
                        </div>
                    </div>
                ) : (
                    <VideoPlayer
                        videoPath={videoPath}
                        currentTime={currentTime}
                        onTimeUpdate={setCurrentTime}
                        onDurationChange={setDuration}
                        overlayTexts={getOverlayTexts()}
                    />
                )}
            </div>

            {/* Sidebar */}
            <div className="sidebar-area glass-panel">
                <Sidebar
                    config={config}
                    onConfigChange={handleConfigChange}
                    onRunAlignment={handleRunAlignment}
                    onExport={handleExport}
                    loading={loading}
                    jobId={jobId}
                    stageData={stageData}
                    selectedStage={selectedStage}
                    onSelectStage={setSelectedStage}
                    latestStage={latestStage}
                    stage={stage}
                />
            </div>

            {/* Timeline */}
            <div className="timeline-area glass-panel" style={{ display: 'flex', flexDirection: 'column' }}>
                <div style={{ padding: '0 12px 6px 12px', display: 'flex', justifyContent: 'flex-end', gap: '8px', zIndex: 10 }}>
                    <button onClick={handleUndo} disabled={historyIndex <= 0} style={{ padding: '2px 8px', fontSize: '0.8rem', cursor: historyIndex <= 0 ? 'default' : 'pointer' }}>Undo</button>
                    <button onClick={handleRedo} disabled={historyIndex >= history.length - 1} style={{ padding: '2px 8px', fontSize: '0.8rem', cursor: historyIndex >= history.length - 1 ? 'default' : 'pointer' }}>Redo</button>
                </div>
                <div style={{ flex: 1, overflow: 'hidden' }}>
                    <Timeline
                        currentTime={currentTime}
                        duration={duration}
                        tracks={tracks}
                        overlayTracks={overlayTracks}
                        onTrackToggle={(trackId) => {
                            setOverlayTracks(prev => {
                                if (prev.includes(trackId)) return prev.filter(id => id !== trackId);
                                if (prev.length >= 2) return prev;
                                return [...prev, trackId];
                            });
                        }}
                        onTimeScrub={handleTimeScrub}
                        onBlockDrag={handleBlockDrag}
                        onBlockEdit={handleBlockEdit}
                        whisperDisplayMode={whisperDisplayMode}
                        onWhisperModeToggle={() => setWhisperDisplayMode(p => p === 'translated' ? 'original' : 'translated')}
                    />
                </div>
            </div>

            {/* File Picker Modal */}
            <FilePicker
                isOpen={pickerOpen}
                onClose={() => setPickerOpen(false)}
                onSelect={handleFileSelect}
                filter={pickerFilter}
                title={pickerTitle}
            />
        </div>
    );
}

export default App;
