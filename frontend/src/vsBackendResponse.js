import React, { useState, useEffect } from "react";
import "./vsBackendResponse.css";

const VsBackendResponse = ({ repo, onClose }) => {
  const [loading, setLoading] = useState(true);
  const [responseData, setResponseData] = useState(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const response = await fetch("http://127.0.0.1:5000/api/upload_to_vs", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ repo }),
        });

        const data = await response.json();
        setResponseData(data);
      } catch (error) {
        setResponseData({ error: "Failed to fetch response from backend" });
      } finally {
        setLoading(false);
      }
    };

    fetchData();
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
              {responseData?.error ? (
                <p className="error-message">{responseData.error}</p>
              ) : (
                <pre>{JSON.stringify(responseData, null, 2)}</pre>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default VsBackendResponse;
