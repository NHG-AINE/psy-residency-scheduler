import ConnectionStatus from './components/ConnectionStatus'

export default function App() {
  return (
    <>
      <a href="#main" className="skip-link">Skip to workspace</a>
      <header className="site-header">
        <a href="/" className="brand" aria-label="PSY Residency Scheduler home">
          <span className="brand-mark" aria-hidden="true">PSY</span>
          <span>Residency scheduler</span>
        </a>
        <span className="workspace-label">Local workspace</span>
      </header>

      <main id="main" className="site-main" tabIndex={-1}>
        <div className="page-heading">
          <h1>Posting timetable</h1>
          <p>NHG Psychiatry Residency Programme</p>
        </div>

        <section className="workspace-panel" aria-labelledby="workspace-title">
          <div className="panel-heading">
            <h2 id="workspace-title">Programme workspace</h2>
            <span className="badge">Getting started</span>
          </div>
          <div className="empty-workspace">
            <svg className="calendar-icon" viewBox="0 0 24 24" aria-hidden="true">
              <path d="M4 5h16v15H4zM8 3v4m8-4v4M4 10h16M8 14h2m4 0h2m-8 3h2m4 0h2" />
            </svg>
            <h3>Your timetable starts here</h3>
            <p>
              This is the application foundation. Workbook import and posting
              allocation will be added in later steps.
            </p>
          </div>
          <ConnectionStatus />
        </section>
      </main>
    </>
  )
}
