import React, { useState, useEffect } from "react";
import "./vsBackendResponse.css";

const VsBackendResponse = ({ repo, onClose }) => {
  const [loading, setLoading] = useState(true);
  const [responseData, setResponseData] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    const fetchData = async () => {
      try {
        const response = await fetch("http://127.0.0.1:5000/api/generate_outline", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ repo }),
          signal: controller.signal
        });

        const reader = response.body.getReader();
        const decoder = new TextDecoder("utf-8");

        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          
          const chunk = decoder.decode(value, { stream: true });
          const lines = chunk.split('\n');
          
          for (const line of lines) {
            if (line.startsWith('data: ')) {
              try {
                const data = JSON.parse(line.slice(6));
                setResponseData(prev => prev + (data.content || ''));
              } catch (e) {
                console.error('Error parsing JSON:', e);
              }
            }
          }
        }
      } catch (error) {
        if (error.name === 'AbortError') {
          console.log('Fetch aborted');
        } else {
          console.error('Error:', error);
          setResponseData("Error fetching response from assistant");
        }
      } finally {
        setLoading(false);
      }
    };

    fetchData();

    return () => {
      controller.abort();
    };
  }, [repo]);

  return (
    <div className="modal-overlay">
      <div className="modal-content">
        <button className="close-button" onClick={onClose}>
          ✖
        </button>
        {loading ? (
          <div className="loading-spinner">Loading...</div>
        ) : (
          <div className="response-content">
            <h3>Response from Backend</h3>
            <div className="scrollable-content">
              {responseData.includes("error") ? (
                <p className="error-message">{responseData}</p>
              ) : (
                <pre>{responseData}</pre>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default VsBackendResponse;
