import React, { useState, useEffect, useCallback, useRef } from 'react';

function FilePicker({ isOpen, onClose, onSelect, filter, title }) {
    const [currentDir, setCurrentDir] = useState(null);
    const [parentDir, setParentDir] = useState(null);
    const [entries, setEntries] = useState([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [selectedIndex, setSelectedIndex] = useState(-1);
    const listRef = useRef(null);

    const browse = useCallback(async (dir) => {
        setLoading(true);
        setError(null);
        setSelectedIndex(-1);
        try {
            const params = new URLSearchParams();
            if (dir) params.set('dir', dir);
            if (filter) params.set('filter', filter);
            const resp = await fetch(`/api/browse?${params}`);
            if (!resp.ok) {
                const data = await resp.json();
                throw new Error(data.detail || `HTTP ${resp.status}`);
            }
            const data = await resp.json();
            setCurrentDir(data.current_dir);
            setParentDir(data.parent_dir);
            setEntries(data.entries);
        } catch (e) {
            setError(e.message);
        } finally {
            setLoading(false);
        }
    }, [filter]);

    useEffect(() => {
        if (isOpen) {
            browse(null);
        }
    }, [isOpen, browse]);

    const handleEntryClick = (entry) => {
        if (entry.is_dir) {
            browse(entry.path);
        } else {
            onSelect(entry.path);
            onClose();
        }
    };

    const handleKeyDown = useCallback((e) => {
        if (!isOpen) return;

        if (e.key === 'Escape') {
            onClose();
            return;
        }

        const fileEntries = entries;
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            setSelectedIndex(prev => Math.min(prev + 1, fileEntries.length - 1));
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            setSelectedIndex(prev => Math.max(prev - 1, 0));
        } else if (e.key === 'Enter' && selectedIndex >= 0) {
            e.preventDefault();
            handleEntryClick(fileEntries[selectedIndex]);
        } else if (e.key === 'Backspace' && parentDir) {
            e.preventDefault();
            browse(parentDir);
        }
    }, [isOpen, entries, selectedIndex, parentDir, browse, onClose]);

    useEffect(() => {
        if (isOpen) {
            window.addEventListener('keydown', handleKeyDown);
            return () => window.removeEventListener('keydown', handleKeyDown);
        }
    }, [isOpen, handleKeyDown]);

    useEffect(() => {
        if (selectedIndex >= 0 && listRef.current) {
            const item = listRef.current.children[selectedIndex];
            if (item) item.scrollIntoView({ block: 'nearest' });
        }
    }, [selectedIndex]);

    if (!isOpen) return null;

    return (
        <div className="filepicker-overlay" onClick={onClose}>
            <div className="filepicker-modal glass-panel" onClick={e => e.stopPropagation()}>
                <div className="filepicker-header">
                    <h3>{title || 'Select File'}</h3>
                    <button className="filepicker-close" onClick={onClose}>×</button>
                </div>

                <div className="filepicker-path">
                    {parentDir && (
                        <button className="filepicker-up" onClick={() => browse(parentDir)}>
                            ↑ Up
                        </button>
                    )}
                    <span className="filepicker-dir">{currentDir || '...'}</span>
                </div>

                {error && <div className="filepicker-error">{error}</div>}

                <div className="filepicker-list" ref={listRef}>
                    {loading ? (
                        <div className="filepicker-loading">Loading...</div>
                    ) : entries.length === 0 ? (
                        <div className="filepicker-empty">No matching files</div>
                    ) : entries.map((entry, i) => (
                        <div
                            key={entry.path}
                            className={`filepicker-entry ${selectedIndex === i ? 'selected' : ''}`}
                            onClick={() => handleEntryClick(entry)}
                            onDoubleClick={() => handleEntryClick(entry)}
                        >
                            <span className="filepicker-icon">{entry.is_dir ? '📁' : '📄'}</span>
                            <span className="filepicker-name">{entry.name}</span>
                            {!entry.is_dir && entry.size_mb != null && (
                                <span className="filepicker-size">{entry.size_mb} MB</span>
                            )}
                        </div>
                    ))}
                </div>
            </div>
        </div>
    );
}

export default FilePicker;
