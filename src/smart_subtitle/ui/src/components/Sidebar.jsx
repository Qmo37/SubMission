import React from 'react';

function Tooltip({ text }) {
    return (
        <span className="tooltip-wrapper">
            <span className="tooltip-trigger">?</span>
            <span className="tooltip-content">{text}</span>
        </span>
    );
}

function Sidebar({ config, onConfigChange, onRunAlignment, onExport, loading, jobId, stageData, selectedStage, onSelectStage, latestStage, stage }) {
    if (!config) {
        return (
            <div className="sidebar" style={{ display: 'flex', flexDirection: 'column', height: '100%', padding: '20px' }}>
                <p style={{ color: 'var(--text-secondary)' }}>Loading config...</p>
            </div>
        );
    }

    const am = config.anchor_mapper || {};
    const fa = config.fine_alignment || {};

    const stages = [
        { num: '5', label: 'Align', tooltip: 'Matches each subtitle line to its Whisper audio segment using text similarity + time distance, with chronological ordering constraints.' },
        { num: '6', label: 'Merge', tooltip: 'Merges sources: matched lines get Whisper timing, unmatched lines interpolate from anchor offsets. Resolves overlaps.' },
        { num: '7', label: 'Fill', tooltip: 'Fills gaps — Whisper audio with no subtitle gets LLM-translated using surrounding context.' },
    ];

    return (
        <div className="sidebar" style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
            <div style={{ padding: '20px 20px 15px 20px', borderBottom: '1px solid var(--border-subtle)', background: 'rgba(25, 26, 30, 0.4)', zIndex: 10 }}>
                <div style={{ display: 'flex', alignItems: 'center', marginBottom: '15px' }}>
                    <h2 style={{ fontSize: '1.1rem' }}>Parameters</h2>
                    <Tooltip text="7-stage pipeline: 1) Extract audio 2) Whisper transcription 3) LLM reference translation 4) Anchor mapping (consensus voting) 5) Fine alignment (line-to-segment matching) 6) Merge (combine sources, resolve overlaps) 7) Gap filling (LLM translation for uncovered segments)." />
                </div>

                {/* Action Buttons */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                    <button
                        className="primary"
                        style={{ width: '100%' }}
                        onClick={onRunAlignment}
                        disabled={loading}
                    >
                        {loading ? 'Running...' : 'Run Pipeline'}
                    </button>
                    <button
                        style={{ width: '100%' }}
                        onClick={onExport}
                        disabled={!jobId || !stageData || Object.keys(stageData).length === 0}
                    >
                        Export .srt
                    </button>
                </div>
            </div>

            {/* Scrollable Content */}
            <div style={{ padding: '15px 20px 20px 20px', overflowY: 'auto', flex: 1 }}>

                {/* Global Alignment Options */}
                <div style={{ marginBottom: '12px' }}>
                    <h3 style={{ fontSize: '0.85rem', marginBottom: '10px', color: 'var(--text-secondary)' }}>Workflow Options</h3>
                    <div className="control-group">
                        <label>
                            Bilingual Sync Strategy
                            <Tooltip text="If multiple subtitle files are provided, how should they merge? Lexical (Early Binding) is best for mapping regional dialects to the master timestamps. Timestamp (Late Binding) merges purely via final audio alignment timings." />
                        </label>
                        <select
                            value={config.alignment_global?.bilingual_cross_match_strategy || 'lexical'}
                            onChange={e => onConfigChange('alignment_global', 'bilingual_cross_match_strategy', e.target.value)}
                            style={{ width: '100%', padding: '4px', borderRadius: '4px', border: '1px solid var(--border-subtle)', background: 'rgba(255,255,255,0.05)', color: 'white' }}
                        >
                            <option value="lexical">Lexical (Early Binding)</option>
                            <option value="timestamp">Timestamp (Late Binding)</option>
                            <option value="none">Disabled</option>
                        </select>
                    </div>
                </div>

                {/* Transcription params */}
                <div style={{ marginBottom: '12px' }}>
                    <h3 style={{ fontSize: '0.85rem', marginBottom: '10px', color: 'var(--text-secondary)' }}>Transcription</h3>

                    <div className="control-group">
                        <label>Whisper Model</label>
                        <select
                            value={config.transcription?.model || 'small'}
                            onChange={e => onConfigChange('transcription', 'model', e.target.value)}
                            style={{ width: '100%', padding: '4px', borderRadius: '4px', border: '1px solid var(--border-subtle)', background: 'rgba(255,255,255,0.05)', color: 'white' }}
                        >
                            <option value="tiny">Tiny</option>
                            <option value="base">Base</option>
                            <option value="small">Small (Fast)</option>
                            <option value="medium">Medium</option>
                            <option value="large-v2">Large v2</option>
                            <option value="large-v3">Large v3 (Accurate)</option>
                        </select>
                    </div>
                </div>

                {/* Anchor Mapper params */}
                <div style={{ marginBottom: '12px' }}>
                    <h3 style={{ fontSize: '0.85rem', marginBottom: '10px', color: 'var(--text-secondary)' }}>Anchor Mapper</h3>

                    <div className="control-group">
                        <label>Window Size (lines)</label>
                        <input
                            type="number"
                            value={am.window_size ?? 40}
                            onChange={e => onConfigChange('anchor_mapper', 'window_size', parseInt(e.target.value) || 40)}
                        />
                    </div>

                    <div className="control-group">
                        <label>Step Size</label>
                        <input
                            type="number"
                            value={am.step_size ?? 20}
                            onChange={e => onConfigChange('anchor_mapper', 'step_size', parseInt(e.target.value) || 20)}
                        />
                    </div>

                    <div className="control-group">
                        <label>Similarity Threshold</label>
                        <input
                            type="number"
                            step="0.05"
                            value={am.min_sim_threshold ?? 0.3}
                            onChange={e => onConfigChange('anchor_mapper', 'min_sim_threshold', parseFloat(e.target.value) || 0.3)}
                        />
                    </div>

                    <div className="control-group">
                        <label>Cluster Tolerance (s)</label>
                        <input
                            type="number"
                            step="0.5"
                            value={am.cluster_tolerance ?? 2.5}
                            onChange={e => onConfigChange('anchor_mapper', 'cluster_tolerance', parseFloat(e.target.value) || 2.5)}
                        />
                    </div>

                    <div className="control-group">
                        <label>Min Cluster Score</label>
                        <input
                            type="number"
                            step="0.1"
                            value={am.min_cluster_score ?? 1.2}
                            onChange={e => onConfigChange('anchor_mapper', 'min_cluster_score', parseFloat(e.target.value) || 1.2)}
                        />
                    </div>
                </div>

                {/* Fine Alignment params */}
                <div style={{ marginBottom: '12px' }}>
                    <h3 style={{ fontSize: '0.85rem', marginBottom: '10px', color: 'var(--text-secondary)' }}>Fine Alignment</h3>

                    <div className="control-group">
                        <label>Text Weight</label>
                        <input
                            type="number"
                            step="0.1"
                            value={fa.text_weight ?? 0.5}
                            onChange={e => onConfigChange('fine_alignment', 'text_weight', parseFloat(e.target.value) || 0.5)}
                        />
                    </div>

                    <div className="control-group">
                        <label>Time Weight</label>
                        <input
                            type="number"
                            step="0.1"
                            value={fa.time_weight ?? 0.5}
                            onChange={e => onConfigChange('fine_alignment', 'time_weight', parseFloat(e.target.value) || 0.5)}
                        />
                    </div>

                    <div className="control-group">
                        <label>Time Tolerance (s)</label>
                        <input
                            type="number"
                            step="0.5"
                            value={fa.time_tolerance ?? 5.0}
                            onChange={e => onConfigChange('fine_alignment', 'time_tolerance', parseFloat(e.target.value) || 5.0)}
                        />
                    </div>

                    <div className="control-group">
                        <label>Gap Penalty Weight</label>
                        <input
                            type="number"
                            step="0.05"
                            value={fa.gap_penalty_weight ?? 0.2}
                            onChange={e => onConfigChange('fine_alignment', 'gap_penalty_weight', parseFloat(e.target.value) || 0.2)}
                        />
                    </div>
                </div>

                {/* Stage Selector */}
                <div style={{ marginBottom: '12px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', marginBottom: '8px' }}>
                        <h3 style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>View Stage</h3>
                    </div>
                    <div className="stage-selector">
                        {stages.map(s => (
                            <button
                                key={s.num}
                                className={`stage-btn ${selectedStage === s.num ? 'active' : ''}`}
                                disabled={!stageData || !stageData[s.num]}
                                onClick={() => onSelectStage(s.num)}
                            >
                                {s.num}: {s.label}
                                <Tooltip text={s.tooltip} />
                            </button>
                        ))}
                    </div>
                    {latestStage > 0 && latestStage < 7 && (
                        <p style={{ fontSize: '0.75rem', color: 'var(--accent-blue)', marginTop: '4px' }}>
                            {stage || `Stage ${latestStage}/7 complete...`}
                        </p>
                    )}
                </div>

            </div>
        </div>
    );
}

export default Sidebar;
