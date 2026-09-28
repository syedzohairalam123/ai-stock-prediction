import { useCallback, useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import axios from 'axios'

const api = axios.create({ baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8000' })

type Block = { available: boolean; reason?: string; [k: string]: unknown }

type Analytics = {
  symbol: string
  available: boolean
  data: { observations: number; source?: string; status?: string; start?: string; end?: string; error?: string }
  stationarity: Block
  returnsStationarity: Block
  distribution: Block
  goodnessOfFit: Block
  moments: Block
  volatility: Block
  tailRisk: Block
  drawdown: Block
  regimeHint: { preferredModel?: string; why?: string }
  riskOfRuin: Block
  disclaimer: string
}

async function fetchAnalytics(ticker: string): Promise<Analytics> {
  const { data } = await api.get(`/api/quant/instruments/${encodeURIComponent(ticker)}/analytics`)
  return data
}

function Stat({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <div className="quant-stat" title={hint}>
      <span className="quant-stat-label">{label}</span>
      <span className="quant-stat-value">{value ?? '—'}</span>
    </div>
  )
}

function BlockCard({ title, block, children }: { title: string; block: Block; children?: React.ReactNode }) {
  if (!block?.available) {
    return (
      <section className="quant-card quant-card--unavailable">
        <h3>{title}</h3>
        <p className="quant-reason">{block?.reason || 'Not available for this sample.'}</p>
      </section>
    )
  }
  return (
    <section className="quant-card">
      <h3>{title}</h3>
      {children}
    </section>
  )
}

function fmt(v: unknown, digits = 4): string {
  const n = typeof v === 'number' ? v : Number(v)
  if (!Number.isFinite(n)) return '—'
  return n.toFixed(digits)
}

function StationarityBody({ block }: { block: Block }) {
  const adf = block.levelsAdf as Block | undefined
  const adfR = block.returnsAdf as Block | undefined
  const vr = block.varianceRatio as Block | undefined
  const hurst = block.hurst as Block | undefined
  const verdict = block.verdict as { headline?: string; note?: string; guidance?: string } | undefined
  return (
    <>
      <div className="quant-grid">
        <Stat label="ADF (levels) p" value={adf?.available ? fmt(adf.pValue, 4) : 'n/a'} hint={String(adf?.conclusion ?? '')} />
        <Stat label="ADF (returns) p" value={adfR?.available ? fmt(adfR.pValue, 4) : 'n/a'} hint={String(adfR?.conclusion ?? '')} />
        <Stat label="Hurst" value={hurst?.available ? fmt(hurst.hurst, 3) : 'n/a'} hint={String(hurst?.reading ?? '')} />
      </div>
      {vr?.available && Array.isArray(vr.results) && (
        <table className="quant-table">
          <thead><tr><th>q</th><th>VR</th><th>p</th><th>Reading</th></tr></thead>
          <tbody>
            {(vr.results as Array<{ period: number; varianceRatio: number; pValue: number | null; reading: string; significant: boolean }>).map((r) => (
              <tr key={r.period} className={r.significant ? 'is-significant' : undefined}>
                <td>{r.period}</td><td>{fmt(r.varianceRatio, 3)}</td><td>{r.pValue == null ? '—' : fmt(r.pValue, 4)}</td><td>{r.reading}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {verdict?.headline && <p className="quant-note"><strong>{verdict.headline}</strong> — {verdict.note} {verdict.guidance}</p>}
    </>
  )
}

function TailBody({ block }: { block: Block }) {
  const levels = (block.levels as Array<Record<string, any>>) || []
  return (
    <>
      {levels.map((lv) => (
        <div key={lv.confidenceLevel} className="quant-var-row">
          <strong>{Math.round(lv.confidenceLevel * 100)}%</strong>
          <span>H {fmt(lv.historic?.var)}</span>
          <span>N {fmt(lv.parametricNormal?.var)}</span>
          <span>t {(lv.parametricStudentT?.var != null) ? fmt(lv.parametricStudentT.var) : '—'}</span>
          <span>CF {(lv.cornishFisher?.var != null) ? fmt(lv.cornishFisher.var) : '—'}</span>
        </div>
      ))}
      <p className="quant-note">{String(block.convention ?? '')} {String((block.tailShape as any)?.whySpreadMatters ?? '')}</p>
    </>
  )
}

export default function QuantLabPage() {
  const [ticker, setTicker] = useState('AAPL')
  const [input, setInput] = useState('AAPL')
  const [benchmark, setBenchmark] = useState('SPY')
  const { data, isFetching, error, refetch } = useQuery({
    queryKey: ['quant-analytics', ticker],
    queryFn: () => fetchAnalytics(ticker),
    retry: 1,
  })

  const run = useCallback((e?: React.FormEvent) => {
    e?.preventDefault()
    const t = input.trim().toUpperCase()
    if (t) setTicker(t)
  }, [input])

  useEffect(() => { document.title = `Quant Lab · ${ticker}` }, [ticker])

  const betaUrl = useMemo(
    () => `/api/quant/instruments/${encodeURIComponent(ticker)}/beta?benchmark=${encodeURIComponent(benchmark)}`,
    [ticker, benchmark],
  )

  return (
    <div className="quant-lab">
      <header className="quant-lab-header">
        <div>
          <h1>Quant Lab</h1>
          <p className="quant-sub">Statistical analysis of real market data — every number states its sample and its limitations. Read-only; this page places no orders.</p>
        </div>
        <form className="quant-form" onSubmit={run}>
          <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Symbol (e.g. AAPL, OGDC, BTC-USD, GC=F)" aria-label="Symbol" />
          <button type="submit" disabled={isFetching}>{isFetching ? 'Analysing…' : 'Analyse'}</button>
        </form>
      </header>

      {error && <p className="quant-error">Analytics unavailable: {(error as Error).message}</p>}

      {data && (
        <>
          <div className="quant-meta">
            <span className="quant-symbol">{data.symbol}</span>
            <span>{data.data?.observations ?? 0} real observations</span>
            <span>source: {data.data?.source ?? '—'}</span>
            <span>status: {data.data?.status ?? '—'}</span>
            {data.data?.start && <span>{String(data.data.start).slice(0, 10)} → {String(data.data.end).slice(0, 10)}</span>}
            <a href={betaUrl} onClick={(e) => e.preventDefault()} style={{ display: 'none' }} aria-hidden>beta</a>
          </div>

          <div className="quant-cards">
            <BlockCard title="Stationarity (levels & returns)" block={data.stationarity}>
              <StationarityBody block={data.stationarity} />
            </BlockCard>

            <BlockCard title="Return distribution" block={data.distribution}>
              {(() => {
                const d = data.distribution as any
                return (
                  <>
                    <div className="quant-grid">
                      <Stat label="Skew" value={fmt(d.skew)} />
                      <Stat label="Excess kurtosis" value={fmt(d.excessKurtosis)} />
                      <Stat label="Best by AIC" value={d.bestByAic} hint={d.bestByAicWhy} />
                    </div>
                    <p className="quant-note">{String(data.goodnessOfFit?.interpretation ?? '')}</p>
                  </>
                )
              })()}
            </BlockCard>

            <BlockCard title="Volatility" block={data.volatility}>
              {(() => {
                const v = data.volatility as any
                return (
                  <div className="quant-grid">
                    <Stat label="Annualised" value={`${fmt(v.annualisedVolatilityPct, 2)}%`} />
                    <Stat label="EWMA annualised" value={`${fmt(v.ewmaAnnualisedPct, 2)}%`} hint={`λ=${v.ewmaLambda}`} />
                    <Stat label="Regime" value={String(v.regime ?? '')} />
                  </div>
                )
              })()}
            </BlockCard>

            <BlockCard title="Tail risk (VaR / CVaR)" block={data.tailRisk}>
              <TailBody block={data.tailRisk} />
            </BlockCard>

            <BlockCard title="Drawdown" block={data.drawdown}>
              {(() => {
                const d = data.drawdown as any
                return (
                  <div className="quant-grid">
                    <Stat label="Max drawdown" value={`${fmt(d.maxDrawdownPct, 2)}%`} />
                    <Stat label="Episodes" value={d.drawdownEpisodes} />
                    <Stat label="Recovered" value={d.recovered ? 'yes' : 'open'} />
                    <Stat label="Current DD" value={`${fmt((d.currentDrawdown ?? 0) * 100, 2)}%`} />
                  </div>
                )
              })()}
            </BlockCard>

            <BlockCard title="Model-selection hint" block={{ available: !!data.regimeHint?.preferredModel && data.regimeHint.preferredModel !== 'unknown' } as Block}>
              <p className="quant-note">
                <strong>{data.regimeHint?.preferredModel}</strong> — {data.regimeHint?.why}
              </p>
            </BlockCard>
          </div>

          <p className="quant-disclaimer">{data.disclaimer}</p>
        </>
      )}
    </div>
  )
}
