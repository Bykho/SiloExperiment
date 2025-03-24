import React, { useState, useEffect } from "react";
import ReactMarkdown from 'react-markdown';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import 'katex/dist/katex.min.css';
import "./parallelModal.css";

// Component styling to ensure all text is left-aligned
const textStyles = {
  textAlign: 'left'
};

const ParallelCard = ({ topic, index, repoName }) => {
  const [cardText, setCardText] = useState("");
  const [sectionTitle, setSectionTitle] = useState(`Section ${index + 1}`);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const controller = new AbortController();

    // Extract section title if it exists
    const titleMatch = topic.match(/SECTION_TITLE:\s*([^\n]+)/);
    if (titleMatch && titleMatch[1]) {
      setSectionTitle(titleMatch[1].trim().replace(/[\[\]]/g, ''));
      const contentWithoutTitle = topic.replace(/SECTION_TITLE:[^\n]+\n?/, '').trim();
    } 

    async function fetchStream() {
      try {
        const response = await fetch("http://127.0.0.1:5000/api/dynamic_expand_topic", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ 
            topic,
            repo: { name: repoName } // Include the repository name here
          }),
          signal: controller.signal,
        });

        if (!response.ok) {
          throw new Error(`Server responded with ${response.status}: ${response.statusText}`);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          const chunk = decoder.decode(value, { stream: true });
          buffer += chunk;
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            if (line.startsWith("data: ")) {
              try {
                const content = line.slice(6); // Remove 'data: ' prefix
                const data = JSON.parse(content);
                if (data.error) {
                  setError(data.error);
                } else if (data.content !== undefined) {
                  setCardText(prev => prev + data.content);
                }
              } catch (e) {
                console.error("Error parsing JSON:", e, "Line:", line);
              }
            }
          }
        }
      } catch (error) {
        if (error.name === "AbortError") {
          console.log("Fetch aborted for topic:", topic);
        } else {
          setError(`Error: ${error.message}`);
          console.error("Error:", error);
        }
      } finally {
        setLoading(false);
      }
    }

    fetchStream();

    return () => {
      controller.abort();
    };
  }, [topic, index, repoName]);

  return (
    <div className="parallel-card">
      <div className="card-header">
        <h4>{sectionTitle}</h4>
        {!loading && (
          <div className="card-actions">
            <button className="card-action-button edit-button" title="Edit this section">
              Edit
            </button>
            <button className="card-action-button refresh-button" title="Regenerate this section">
              Refresh
            </button>
          </div>
        )}
      </div>
      {loading && <div className="loading-spinner">Loading...</div>}
      {error && <p className="error-message">{error}</p>}
      <div className="markdown-content" style={textStyles}>
        <ReactMarkdown 
            remarkPlugins={[remarkMath]}
            rehypePlugins={[rehypeKatex]}
            components={{
              p: ({node, ...props}) => <p style={textStyles} {...props} />,
              h1: ({node, ...props}) => <h1 style={textStyles} {...props} />,
              h2: ({node, ...props}) => <h2 style={textStyles} {...props} />,
              h3: ({node, ...props}) => <h3 style={textStyles} {...props} />,
              h4: ({node, ...props}) => <h4 style={textStyles} {...props} />,
              li: ({node, ...props}) => <li style={textStyles} {...props} />,
              ul: ({node, ...props}) => <ul style={textStyles} {...props} />,
              ol: ({node, ...props}) => <ol style={textStyles} {...props} />
            }}
        >
            {cardText}
        </ReactMarkdown>
      </div>
    </div>
  );
};

const ParallelModal = ({ text, repoName, onClose }) => {
  const [sections, setSections] = useState([]);
  const [isAddingSectionOpen, setIsAddingSectionOpen] = useState(false);
  const [newSectionTitle, setNewSectionTitle] = useState("");

  useEffect(() => {
    const extractedSections = text.split("---").filter(t => t.trim().length > 10);
    setSections(extractedSections);
  }, [text]);

  const handleAddSection = () => {
    if (newSectionTitle.trim()) {
      setSections([...sections, `---SECTION_TITLE: ${newSectionTitle.trim()}\n\nCustom section added by user.`]);
      setNewSectionTitle("");
      setIsAddingSectionOpen(false);
    }
  };

  const handleRemoveSection = (index) => {
    const updatedSections = [...sections];
    updatedSections.splice(index, 1);
    setSections(updatedSections);
  };

  const toggleAddSection = () => {
    setIsAddingSectionOpen(!isAddingSectionOpen);
  };

  // Handle key commands (Enter to add section)
  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && newSectionTitle.trim()) {
      e.preventDefault();
      handleAddSection();
    }
  };

  return (
    <div className="modal-overlay">
      <div className="parallel-modal-content">
        <div className="modal-header">
          <h3>Portfolio Section Expansion</h3>
          <div className="header-actions">
            <button 
              className="add-section-button"
              onClick={toggleAddSection}
              title="Add a new section"
            >
              Add Section
            </button>
            <button className="close-button" onClick={onClose}>✖</button>
          </div>
        </div>
        
        {isAddingSectionOpen && (
          <div className="add-section-form">
            <input
              type="text"
              value={newSectionTitle}
              onChange={(e) => setNewSectionTitle(e.target.value)}
              placeholder="Enter section title"
              className="section-title-input"
              onKeyDown={handleKeyDown}
              aria-label="New section title"
            />
            <button 
              onClick={handleAddSection}
              disabled={!newSectionTitle.trim()}
              className="confirm-add-button"
            >
              Add
            </button>
            <button 
              onClick={() => setIsAddingSectionOpen(false)}
              className="cancel-add-button"
            >
              Cancel
            </button>
          </div>
        )}
        
        <div className="parallel-grid">
          {sections.map((topic, idx) => (
            <div key={idx} className="card-container">
              <ParallelCard 
                topic={topic} 
                index={idx} 
                repoName={repoName} // Pass the repository name to the card
              />
              <button 
                className="remove-section-button" 
                onClick={() => handleRemoveSection(idx)}
                title="Remove this section"
                aria-label="Remove section"
              >
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

export default ParallelModal;