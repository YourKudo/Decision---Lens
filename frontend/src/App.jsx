import { useEffect, useRef, useState } from 'react'
import './App.css'

const projectName = 'Verdict Forge'

const starterPrompts = [
  'Should I buy iPhone 17?',
  'Should I wait for the next MacBook Air?',
  'Is switching from Android to iPhone worth it?',
]

function App() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const scrollRef = useRef(null)

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: 'smooth',
    })
  }, [messages, loading])

  const updateBotMessage = (messageId, updater) => {
    setMessages((current) =>
      current.map((message) =>
        message.id === messageId ? { ...message, ...updater(message) } : message,
      ),
    )
  }

  const sendMessage = async (preset) => {
    const query = (preset ?? input).trim()
    if (!query || loading) {
      return
    }

    const userMessage = { id: `${Date.now()}-user`, type: 'user', text: query }
    const botMessageId = `${Date.now()}-bot`

    setMessages((current) => [
      ...current,
      userMessage,
      {
        id: botMessageId,
        type: 'bot',
        status: 'Starting analysis...',
        events: [],
        data: null,
      },
    ])
    setInput('')
    setLoading(true)

    try {
      const response = await fetch('http://127.0.0.1:8000/analyze/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query,
          max_results_per_source: 5,
          use_cache: true,
        }),
      })

      if (!response.ok || !response.body) {
        throw new Error('The backend did not return a stream.')
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) {
          break
        }

        buffer += decoder.decode(value, { stream: true })
        const parts = buffer.split('\n\n')
        buffer = parts.pop() ?? ''

        for (const part of parts) {
          const line = part.split('\n').find((entry) => entry.startsWith('data: '))
          if (!line) {
            continue
          }

          const payload = JSON.parse(line.slice(6))
          updateBotMessage(botMessageId, (message) => {
            const next = {
              status: payload.message ?? message.status,
              events:
                payload.event === 'done'
                  ? message.events
                  : [...message.events, payload.message].slice(-4),
            }

            if (payload.event === 'final' || payload.event === 'cached') {
              next.data = payload.data?.final ?? null
            }

            return next
          })
        }
      }
    } catch (error) {
      updateBotMessage(botMessageId, () => ({
        status: 'Analysis failed.',
        events: ['I could not complete the request.'],
        data: null,
        error: error.message,
      }))
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className="app-shell">
      <section className="hero-panel">
        <p className="eyebrow">{projectName}</p>
        <h1>Decision intelligence for the questions you do not want to guess on.</h1>
        <p className="hero-copy">
          Search one real-life choice and get a darker, sharper brief built from public
          conversations across Reddit, YouTube, and Quora. No fluff, just sentiment,
          trade-offs, source links, and a signal you can act on.
        </p>
        <div className="prompt-row">
          {starterPrompts.map((prompt) => (
            <button
              key={prompt}
              className="prompt-chip"
              onClick={() => sendMessage(prompt)}
              disabled={loading}
            >
              {prompt}
            </button>
          ))}
        </div>
      </section>

      <section className="chat-panel">
        <div className="panel-heading">
          <p className="section-kicker">Live Workspace</p>
          <h2>{messages.length ? 'Search the crowd, then read the signal.' : 'Ask what the internet really thinks.'}</h2>
          <p className="section-copy">
            Your answer streams in as the backend scrapes sources, extracts opinions,
            and shapes them into a decision brief.
          </p>
        </div>
        <div className="chat-log" ref={scrollRef}>
          {messages.length === 0 ? (
            <div className="empty-state">
              <p className="empty-title">Start with a decision that has real stakes.</p>
              <p className="empty-copy">
                Try a purchase decision, timing question, or platform switch and this
                workspace will turn scattered public opinion into something you can scan fast.
              </p>
            </div>
          ) : (
            messages.map((message) => (
              <article key={message.id} className={`message-card ${message.type}`}>
                {message.type === 'user' ? <p>{message.text}</p> : <BotResponse message={message} />}
              </article>
            ))
          )}
        </div>

        <div className="composer">
          <textarea
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder="Ask a decision question..."
            rows={2}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault()
                sendMessage()
              }
            }}
          />
          <button className="send-button" onClick={() => sendMessage()} disabled={loading}>
            {loading ? 'Analyzing...' : 'Analyze'}
          </button>
        </div>
      </section>
    </main>
  )
}

function BotResponse({ message }) {
  if (!message.data) {
    return (
      <div className="stream-card">
        <p className="status-line">{message.status}</p>
        {message.events.length > 0 && (
          <ul className="status-list">
            {message.events.map((event) => (
              <li key={event}>{event}</li>
            ))}
          </ul>
        )}
        {message.error && <p className="error-text">{message.error}</p>}
      </div>
    )
  }

  const { data } = message

  return (
    <div className="report">
      <div className="report-topline">
        <div>
          <p className="report-label">Decision Topic</p>
          <h2>{data.decision_topic}</h2>
        </div>
        <div className="score-orb">
          <span>{data.decision_score}</span>
          <small>Score</small>
        </div>
      </div>

      <p className="summary">{data.summary}</p>

      <div className="metrics-grid">
        <MetricCard label="Confidence" value={`${data.confidence}%`} />
        <MetricCard label="Buy" value={`${data.what_people_say.buy}%`} />
        <MetricCard label="Wait" value={`${data.what_people_say.wait}%`} />
        <MetricCard label="Not Buy" value={`${data.what_people_say.not_buy}%`} />
      </div>

      <InsightVisualization data={data} />

      <div className="insight-grid">
        <InfoCard title="Pros" items={data.pros} tone="positive" />
        <InfoCard title="Cons" items={data.cons} tone="negative" />
      </div>

      <div className="insight-grid secondary-grid">
        <InfoCard title="Key Insights" items={data.key_insights} />
        <SourceBreakdown distribution={data.source_distribution} />
      </div>

      <SourceList sources={data.sources_used} />
    </div>
  )
}

function InsightVisualization({ data }) {
  const stanceData = [
    { label: 'Buy', value: data.what_people_say.buy, tone: 'buy' },
    { label: 'Wait', value: data.what_people_say.wait, tone: 'wait' },
    { label: 'Not Buy', value: data.what_people_say.not_buy, tone: 'not-buy' },
  ]

  const sourceTotal =
    data.source_distribution.reddit +
    data.source_distribution.youtube +
    data.source_distribution.quora

  const sourceData = [
    { label: 'Reddit', value: data.source_distribution.reddit, tone: 'reddit' },
    { label: 'YouTube', value: data.source_distribution.youtube, tone: 'youtube' },
    { label: 'Quora', value: data.source_distribution.quora, tone: 'quora' },
  ].map((item) => ({
    ...item,
    percent: sourceTotal ? Math.round((item.value / sourceTotal) * 100) : 0,
  }))

  return (
    <section className="viz-board">
      <div className="viz-card">
        <h3>General Insights</h3>
        <p>How the overall recommendation leans after scraping and summarizing public discussion.</p>
        <div className="viz-list">
          {stanceData.map((item) => (
            <div key={item.label} className="viz-row">
              <div className="viz-label-line">
                <span>{item.label}</span>
                <strong>{item.value}%</strong>
              </div>
              <div className="viz-track">
                <div className={`viz-fill ${item.tone}`} style={{ width: `${item.value}%` }} />
              </div>
            </div>
          ))}
        </div>
      </div>
      <div className="viz-card">
        <h3>Source Weight</h3>
        <p>Where the scraped evidence came from for this answer.</p>
        <div className="viz-list compact">
          {sourceData.map((item) => (
            <div key={item.label} className="viz-row">
              <div className="viz-label-line">
                <span>{item.label}</span>
                <strong>{item.percent}%</strong>
              </div>
              <div className="viz-track">
                <div className={`viz-fill ${item.tone}`} style={{ width: `${item.percent}%` }} />
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

function MetricCard({ label, value }) {
  return (
    <div className="metric-card">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  )
}

function InfoCard({ title, items, tone = 'neutral' }) {
  return (
    <section className={`info-card ${tone}`}>
      <h3>{title}</h3>
      <ul>
        {items?.length ? items.map((item) => <li key={item}>{item}</li>) : <li>No strong signal yet.</li>}
      </ul>
    </section>
  )
}

function SourceBreakdown({ distribution }) {
  return (
    <section className="info-card source-overview">
      <h3>Source Breakdown</h3>
      <div className="source-strip">
        <SourcePill label="Reddit" value={distribution.reddit} />
        <SourcePill label="YouTube" value={distribution.youtube} />
        <SourcePill label="Quora" value={distribution.quora} />
      </div>
    </section>
  )
}

function SourcePill({ label, value }) {
  return (
    <div className="source-pill">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  )
}

function SourceList({ sources }) {
  return (
    <section className="sources-card">
      <div className="sources-header">
        <h3>Sources Used</h3>
        <p>These are the scraped discussions that informed the answer.</p>
      </div>
      <div className="sources-list">
        {sources?.length ? (
          sources.map((source) => (
            <article key={`${source.platform}-${source.url}-${source.title}`} className="source-item">
              <div className="source-meta">
                <span className={`platform-badge ${source.platform}`}>{source.platform}</span>
                <span>{source.comments_analyzed} comments analyzed</span>
              </div>
              <h4>{source.title}</h4>
              <p>{source.snippet}</p>
              {source.url && (
                <a href={source.url} target="_blank" rel="noreferrer">
                  Open source
                </a>
              )}
            </article>
          ))
        ) : (
          <p className="sources-empty">No source references available yet.</p>
        )}
      </div>
    </section>
  )
}

export default App
