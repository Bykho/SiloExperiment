import React, { useState, useEffect, useRef } from "react";
import ReactMarkdown from 'react-markdown';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import 'katex/dist/katex.min.css'; 
import "./vsBackendResponse.css";
import ParallelModal from "./parallelModal";

const AssistantResponse = ({ repo, onClose }) => {
  const [text, setText] = useState("");
  const [editableText, setEditableText] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showParallelModal, setShowParallelModal] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const scrollableRef = useRef(null);
  const initialRenderRef = useRef(true);

  useEffect(() => {
    console.log("Starting fetch for repo:", repo);
    
    // Create an AbortController to handle cleanup
    const controller = new AbortController();
    
    async function fetchStream() {
      try {
        const response = await fetch("http://127.0.0.1:5000/api/generate_outline", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ repo }),
          signal: controller.signal
        });

        if (!response.ok) {
          throw new Error(`Server responded with ${response.status}: ${response.statusText}`);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        
        // Process the stream
        console.log("Stream connected, processing...");
        
        // Set up a buffer for incomplete lines
        let buffer = '';
        
        while (true) {
          const { value, done } = await reader.read();
          if (done) {
            console.log("Stream complete");
            break;
          }
          
          // Decode the chunk and append to buffer
          const chunk = decoder.decode(value, { stream: true });
          buffer += chunk;
          
          // Process complete lines in the buffer
          const lines = buffer.split('\n');
          
          // Save the last (potentially incomplete) line back to the buffer
          buffer = lines.pop() || '';
          
          for (const line of lines) {
            if (line.startsWith('data: ')) {
              try {
                const content = line.slice(6); // Remove 'data: ' prefix
                const data = JSON.parse(content);
                
                if (data.error) {
                  setError(data.error);
                } else if (data.content !== undefined) {
                  setText(prev => prev + data.content);
                  
                  // Auto-scroll to bottom as content comes in
                  if (scrollableRef.current) {
                    scrollableRef.current.scrollTop = scrollableRef.current.scrollHeight;
                  }
                }
              } catch (e) {
                console.error('Error parsing JSON:', e, 'Line:', line);
              }
            }
          }
        }
        
        // Once streaming is done, set the editable text to be the same as the final text
        setIsEditing(true);
      } catch (error) {
        if (error.name === 'AbortError') {
          console.log('Fetch aborted');
        } else {
          setError(`Error: ${error.message}`);
          console.error('Error:', error);
        }
      } finally {
        setLoading(false);
      }
    }

    fetchStream();

    return () => {
      console.log("Cleaning up, aborting fetch");
      controller.abort();
    };
  }, [repo]);

  // Effect to sync text with editableText once when loading is complete
  useEffect(() => {
    if (!loading && text && !editableText) {
      setEditableText(text);
    }
  }, [loading, text, editableText]);

  // Handle transition from streaming to editing with a subtle delay
  useEffect(() => {
    if (!loading && isEditing && initialRenderRef.current) {
      initialRenderRef.current = false;
      
      // A slight delay helps create a smoother transition to edit mode
      const timer = setTimeout(() => {
        if (scrollableRef.current) {
          scrollableRef.current.classList.add('edit-mode-active');
        }
      }, 300);
      
      return () => clearTimeout(timer);
    }
  }, [loading, isEditing]);

  // Handle text editing
  const handleTextChange = (e) => {
    setEditableText(e.target.value);
  };

  // Handle key commands (Ctrl+Enter to parallelize)
  const handleKeyDown = (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter' && !loading && text) {
      e.preventDefault();
      setShowParallelModal(true);
    }
  };

  return (
    <div className="modal-overlay">
      <div className="modal-content">
        <button className="close-button" onClick={onClose}>✖</button>
        <h3>Help us plan how we are going to build your portfolio</h3>
        
        <div className="scrollable-content" ref={scrollableRef}>
          {loading && <div className="loading-spinner">Generating outline...</div>}
          {error && <p className="error-message">{error}</p>}
          
          {!loading && isEditing ? (
            <div className="editable-content">
              <div className="edit-mode-indicator">
                You can now refine the outline before parallelization
              </div>
              <textarea
                className="editable-textarea"
                value={editableText}
                onChange={handleTextChange}
                onKeyDown={handleKeyDown}
                spellCheck="false"
                aria-label="Editable outline content"
              />
            </div>
          ) : (
            text && (
              <div className="markdown-content">
                <ReactMarkdown 
                  remarkPlugins={[remarkMath]}
                  rehypePlugins={[rehypeKatex]}
                  components={{
                    pre: ({node, ...props}) => <pre className="streaming-text" {...props} />
                  }}
                >
                  {text}
                </ReactMarkdown>
              </div>
            )
          )}
        </div>
        
        <button 
          className="parallelize-button" 
          onClick={() => setShowParallelModal(true)}
          disabled={loading || !text}
          title="Process each section in parallel (Ctrl+Enter)"
        >
          Parallelize & Expand
        </button>
      </div>
      
      {showParallelModal && (
        <ParallelModal text={editableText} onClose={() => setShowParallelModal(false)} />
      )}
    </div>
  );
};

export default AssistantResponse;