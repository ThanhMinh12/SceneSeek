export default function WelcomeStory() {
  return <div className="welcome-story">
    <p className="welcome-eyebrow">Skip to the good part</p>
    <h1>Less scrubbing.<br /><em>More finding.</em></h1>
    <p className="welcome-description">Find the scene you remember with a description, an image, or a clip.</p>
    <svg className="welcome-art" viewBox="0 0 320 86" fill="none" aria-hidden="true">
      <g className="timeline-frames"><rect x="1" y="12" width="58" height="38" rx="5" /><rect x="69" y="12" width="58" height="38" rx="5" /><rect x="137" y="12" width="58" height="38" rx="5" /><rect x="205" y="12" width="58" height="38" rx="5" /></g>
      <path className="timeline-track" d="M1 66h318" />
      <path className="timeline-selected" d="M137 66h58M166 4v73" />
      <path className="timeline-play" d="m160 23 12 8-12 8Z" />
      <circle className="timeline-play" cx="166" cy="66" r="4" />
    </svg>
  </div>;
}
