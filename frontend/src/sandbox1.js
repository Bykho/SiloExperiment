import React, { useEffect, useState } from "react";
import "./sandbox1.css";
import VsBackendResponse from "./vsBackendResponse";
import AssistantResponse from "./assistantResponse"; // New component for streaming output

const Sandbox1 = () => {
  const [repos, setRepos] = useState([]);
  const [selectedRepo, setSelectedRepo] = useState(null);
  const [showEntryModal, setShowEntryModal] = useState(false);
  const [showAssistantModal, setShowAssistantModal] = useState(false);

  const handleSelectRepo = (repo) => {
    setSelectedRepo(repo.id === selectedRepo ? null : repo);
  };

  const handleBuildEntry = () => {
    setShowEntryModal(true);
  };

  const handleGenerateOutline = () => {
    setShowAssistantModal(true);
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
      {showEntryModal && (
        <VsBackendResponse repo={selectedRepo} onClose={() => setShowEntryModal(false)} />
      )}
      {showAssistantModal && (
        <AssistantResponse repo={selectedRepo} onClose={() => setShowAssistantModal(false)} />
      )}
    </div>
  );
};

export default Sandbox1;
