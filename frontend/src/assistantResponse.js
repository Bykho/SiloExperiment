import React, { useState, useEffect } from "react";
import "./vsBackendResponse.css";  // Reuse the existing CSS

const AssistantResponse = ({ repo, onClose }) => {
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

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
                
                // Log the raw content for debugging
                console.log("Raw content:", content);
                
                const data = JSON.parse(content);
                console.log("Parsed data:", data);
                
                if (data.error) {
                  setError(data.error);
                } else if (data.content !== undefined) {
                  setText(prev => prev + data.content);
                }
              } catch (e) {
                console.error('Error parsing JSON:', e, 'Line:', line);
              }
            }
          }
        }
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

  return (
    <div className="modal-overlay">
      <div className="modal-content">
        <button className="close-button" onClick={onClose}>✖</button>
        <h3>Help us plan how we are going to build your portfolio</h3>
        <div className="scrollable-content">
          {loading && <div className="loading-spinner">Generating outline...</div>}
          {error && <p className="error-message">{error}</p>}
          {text && <pre className="streaming-text">{text}</pre>}
        </div>
      </div>
    </div>
  );
};

export default AssistantResponse;