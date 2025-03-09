import React, { useEffect, useState } from "react";
import "./sandbox1.css";
import VsBackendResponse from "./vsBackendResponse";
import AssistantResponse from "./assistantResponse";

const Sandbox1 = () => {
  const [repos, setRepos] = useState([]);
  const [selectedRepo, setSelectedRepo] = useState(null);
  const [showEntryModal, setShowEntryModal] = useState(false);
  const [showAssistantModal, setShowAssistantModal] = useState(false);
  // New state to track the mode: false = pre‐built, true = dynamic
  const [isDynamicMode, setIsDynamicMode] = useState(false);

  const handleSelectRepo = (repo) => {
    setSelectedRepo(repo.id === selectedRepo ? null : repo);
  };

  const handleBuildEntry = () => {
    setShowEntryModal(true);
  };

  const handleGenerateOutline = () => {
    setShowAssistantModal(true);
  };

  // Handler for the toggle switch
  const handleToggleDynamicMode = () => {
    setIsDynamicMode((prev) => !prev);
  };

  useEffect(() => {
    fetch("http://127.0.0.1:5000/api/repos")
      .then((response) => response.json())
      .then((data) => {
        if (data.repositories) {
          setRepos(data.repositories);
        }
      })
      .catch((error) => {
        console.error("Error fetching repositories:", error);
      });
  }, []);

  return (
    <div className="repo-container">
      {/* New toggle switch for selecting mode */}
      <div className="mode-toggle">
        <label>
          <input
            type="checkbox"
            checked={isDynamicMode}
            onChange={handleToggleDynamicMode}
          />
          Use Dynamic Mode
        </label>
      </div>

      {repos.length > 0 ? (
        <ul className="repo-list">
          {repos.map((repo) => (
            <li
              key={repo.id}
              className={`repo-item ${repo.id === selectedRepo?.id ? "selected" : ""}`}
              onClick={() => handleSelectRepo(repo)}
            >
              {repo.name}
              {selectedRepo?.id === repo.id && (
                <>
                  <button className="build-entry-btn" onClick={handleBuildEntry}>
                    Build Entry?
                  </button>
                  <button className="generate-outline-btn" onClick={handleGenerateOutline}>
                    Generate Outline
                  </button>
                </>
              )}
            </li>
          ))}
        </ul>
      ) : (
        <p>No repositories found</p>
      )}

      {/* Pass the mode flag to the modals */}
      {showEntryModal && (
        <VsBackendResponse
          repo={selectedRepo}
          isDynamicMode={isDynamicMode}
          onClose={() => setShowEntryModal(false)}
        />
      )}
      {showAssistantModal && (
        <AssistantResponse
          repo={selectedRepo}
          isDynamicMode={isDynamicMode}
          onClose={() => setShowAssistantModal(false)}
        />
      )}
    </div>
  );
};

export default Sandbox1;
