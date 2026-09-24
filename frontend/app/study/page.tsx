"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ArrowRight, BookOpen, CalendarCheck, ChartNoAxesCombined, ChevronLeft, Layers, Loader2, Plus, Settings, Sparkles, Target } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Generator } from "@/components/study/generator";
import { ItemEditor, selectClass, SourceNote } from "@/components/study/item-editor";
import { dateLabel, Practice } from "@/components/study/practice";
import { API_BASE_URL } from "@/lib/api";
import { kindLabels, ModelSettings, StudyDeck, StudyDocument, StudyItem, StudyKind, StudyMode, StudySession, StudyStats, studyRequest } from "@/lib/study-api";
import { SUPPORTED_MODELS, useSettingsStore } from "@/stores/settings";

type Tab = "today" | "generate" | "decks" | "progress";
const navigation = [
  { id: "today" as Tab, name: "今日学习", icon: CalendarCheck },
  { id: "generate" as Tab, name: "生成题目", icon: Sparkles },
  { id: "decks" as Tab, name: "卡组管理", icon: Layers },
  { id: "progress" as Tab, name: "学习复盘", icon: ChartNoAxesCombined },
];
const modes: Record<StudyMode, string> = { daily: "每日复习", weak: "薄弱点练习", mistakes: "错题重练" };

export default function StudyPage() {
  const settings = useSettingsStore();
  const provider = SUPPORTED_MODELS.find(m => m.id === settings.model)?.provider || settings.selectedProvider;
  const modelSettings: ModelSettings = { model: settings.model, provider, apiKey: settings.getEffectiveApiKey(), baseUrl: settings.baseUrls[provider] || null };
  const [tab, setTab] = useState<Tab>("today");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [stats, setStats] = useState<StudyStats | null>(null);
  const [decks, setDecks] = useState<StudyDeck[]>([]);
  const [documents, setDocuments] = useState<StudyDocument[]>([]);
  const [deckId, setDeckId] = useState("");
  const [items, setItems] = useState<StudyItem[]>([]);
  const [editing, setEditing] = useState<StudyItem | null>(null);
  const [deckTitle, setDeckTitle] = useState("");
  const [rename, setRename] = useState("");
  const [kind, setKind] = useState<StudyKind | "">("");
  const [point, setPoint] = useState("");
  const [limit, setLimit] = useState(20);
  const [days, setDays] = useState<7 | 30>(7);
  const [record, setRecord] = useState<StudySession | null>(null);
  const [initialDocument, setInitialDocument] = useState("");
  const [variant, setVariant] = useState<StudyItem | null>(null);
  const starting = useRef<{ key: string; id: string } | null>(null);
  const pending = useRef(false);
  const selectedDeck = decks.find(d => d.id === deckId);

  const refresh = useCallback(async () => {
    const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    const [newStats, newDecks] = await Promise.all([
      studyRequest<StudyStats>(`/stats?timezone=${encodeURIComponent(timezone)}`),
      studyRequest<StudyDeck[]>("/decks"),
    ]);
    setStats(newStats);
    setDecks(newDecks);
  }, []);

  useEffect(() => {
    let active = true;
    async function initialize() {
      try {
        await refresh();
        const response = await fetch(`${API_BASE_URL}/api/documents/`);
        if (!response.ok) throw new Error("无法读取知识库文档");
        const docs: StudyDocument[] = await response.json();
        if (!active) return;
        setDocuments(docs);
        const params = new URLSearchParams(window.location.search);
        const document = params.get("document");
        if (document) { setInitialDocument(document); setTab("generate"); }
        const session = params.get("session");
        if (session) {
          const restored = await studyRequest<StudySession>(`/sessions/${session}`);
          if (active) setRecord(restored);
        }
      } catch (err) { if (active) setError(err instanceof Error ? err.message : "加载失败，请检查后端服务"); }
      finally { if (active) setLoading(false); }
    }
    void initialize();
    return () => { active = false; };
  }, [refresh]);

  useEffect(() => {
    let active = true;
    if (deckId) {
      studyRequest<StudyItem[]>(`/decks/${deckId}/items`).then(data => { if (active) setItems(data); })
        .catch(err => { if (active) setError(err.message); });
    }
    return () => { active = false; };
  }, [deckId]);

  async function run(job: () => Promise<void>) {
    if (pending.current) return;
    pending.current = true;
    setBusy(true); setError(""); setNotice("");
    try { await job(); }
    catch (err) { setError(err instanceof Error ? err.message : "操作失败，请稍后重试"); }
    finally { pending.current = false; setBusy(false); }
  }

  async function updateRecord(value: StudySession) {
    setRecord(value);
    window.history.replaceState(null, "", `/study?session=${value.id}`);
    await refresh();
  }

  function start(mode: StudyMode, knowledgePoint = point) {
    void run(async () => {
      const filters = { mode, deck_id: deckId || null, kind: kind || null, knowledge_point: knowledgePoint, limit };
      const key = JSON.stringify(filters);
      if (!starting.current || starting.current.key !== key) starting.current = { key, id: crypto.randomUUID() };
      await updateRecord(await studyRequest<StudySession>("/sessions", "POST", { ...filters, id: starting.current.id }));
      starting.current = null;
    });
  }

  function generateVariant(itemId: string) {
    void run(async () => {
      const item = await studyRequest<StudyItem>(`/items/${itemId}`);
      setVariant(item); setTab("generate"); setRecord(null);
      window.history.replaceState(null, "", "/study");
    });
  }

  const trend = stats?.trend.slice(-days) || [];
  const reviewed = trend.reduce((sum, day) => sum + day.reviewed, 0);
  const choiceCount = trend.reduce((sum, day) => sum + day.choice_count, 0);
  const correctCount = trend.reduce((sum, day) => sum + day.choice_correct, 0);
  const flashCount = trend.reduce((sum, day) => sum + day.flashcard_count, 0);
  const flashRecalled = trend.reduce((sum, day) => sum + day.flashcard_recalled, 0);
  const maxDaily = Math.max(1, ...trend.map(day => day.reviewed));

  return <div className="min-h-screen bg-background text-foreground lg:flex">
    <aside className="border-b bg-sidebar-background p-4 lg:sticky lg:top-0 lg:flex lg:h-screen lg:w-56 lg:shrink-0 lg:flex-col lg:border-r lg:border-b-0 lg:p-5">
      <Link href="/" className="mb-6 inline-flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground"><ChevronLeft className="h-3 w-3" />OpenKnowledge</Link>
      <div className="mb-7 flex items-center gap-3"><div className="rounded-xl bg-emerald-800 p-2.5 text-white"><Layers className="h-5 w-5" /></div><div><h1 className="font-semibold">刷题助手</h1><p className="mt-0.5 text-xs text-muted-foreground">从理解，到记住。</p></div></div>
      <nav aria-label="学习导航" className="flex gap-1 overflow-x-auto lg:flex-col">{navigation.map(({ id, name, icon: Icon }) => <button key={id} disabled={busy} onClick={() => { setTab(id); setRecord(null); setError(""); window.history.replaceState(null, "", "/study"); }} aria-current={!record && tab === id ? "page" : undefined} className={`flex shrink-0 items-center gap-3 rounded-lg px-3 py-3 text-sm transition-colors ${!record && tab === id ? "bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-100" : "text-muted-foreground hover:bg-sidebar-accent"}`}><Icon className="h-4 w-4" />{name}</button>)}</nav>
      <div className="mt-auto hidden space-y-4 pt-10 text-xs text-muted-foreground lg:block"><Link href="/knowledge" className="flex items-center gap-2 hover:text-foreground"><BookOpen className="h-4 w-4" />知识库</Link><Link href="/settings" className="flex items-center gap-2 hover:text-foreground"><Settings className="h-4 w-4" />模型设置</Link><div className="border-t pt-4 leading-6">FSRS 间隔复习<br />目标保留率 90%</div></div>
    </aside>
    <main className="min-w-0 flex-1 px-4 py-6 sm:px-8 lg:px-12 lg:py-10">
      <div className="mx-auto max-w-5xl">
        <header className="mb-8 flex flex-wrap items-center justify-between gap-3 border-b pb-4 text-xs text-muted-foreground"><span>个人学习工作台</span><Link className="flex items-center gap-2 hover:text-foreground" href="/settings"><span className="h-1.5 w-1.5 rounded-full bg-emerald-600" />{settings.model}<Settings className="h-3 w-3" /></Link></header>
        {error && <div role="alert" className="mb-6 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200"><p>{error}</p><Button variant="outline" size="sm" disabled={busy} onClick={() => void run(async () => { await refresh(); if (record) await updateRecord(await studyRequest<StudySession>(`/sessions/${record.id}`)); })}>重新加载</Button></div>}
        {notice && <p role="status" className="mb-6 rounded-xl bg-emerald-50 p-4 text-sm text-emerald-900 dark:bg-emerald-950 dark:text-emerald-100">{notice}</p>}
        {busy && <p role="status" className="mb-4 flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" />正在处理，请稍候…</p>}
        {loading ? <p role="status" className="py-20 text-center text-muted-foreground">正在读取学习记录…</p> : record ? <Practice record={record} settings={modelSettings} busy={busy} run={job => void run(job)} onChange={updateRecord} onExit={() => { setRecord(null); setTab("today"); window.history.replaceState(null, "", "/study"); }} onVariant={generateVariant} /> : <>
          {tab === "today" && <div className="space-y-8">
            <section className="flex flex-wrap items-end justify-between gap-5"><div><p className="text-xs font-medium tracking-widest text-emerald-700 dark:text-emerald-400">DAILY PRACTICE / 今日学习</p><h2 className="mt-3 text-3xl font-semibold tracking-tight sm:text-4xl">温故，才能知新。</h2><p className="mt-3 text-sm text-muted-foreground">先巩固快要忘记的，再为新知识留一点空间。</p></div><Button variant="outline" disabled={busy} onClick={() => { setVariant(null); setTab("generate"); }}><Plus className="mr-2 h-4 w-4" />生成新题</Button></section>
            <section className="grid grid-cols-3 divide-x rounded-2xl border bg-card py-6 sm:py-8">{[["到期复习", stats?.due ?? 0], ["待学新题", stats?.new ?? 0], ["今日已练", stats?.reviewed_today ?? 0]].map(([label, value]) => <div key={label} className="px-4 sm:px-7"><p className="text-xs text-muted-foreground sm:text-sm">{label}</p><p className="mt-3 text-3xl font-medium tabular-nums sm:text-4xl">{value}</p></div>)}</section>
            <section className="rounded-2xl border border-emerald-900 bg-emerald-950 p-6 text-emerald-50 sm:p-8"><div className="flex items-center gap-3"><CalendarCheck className="h-5 w-5" /><h3 className="text-lg font-medium">开始一轮专注练习</h3></div><p className="mt-3 text-sm leading-6 text-emerald-100/75">到期学习与重学优先，其次是遗忘风险较高的复习题，最后补充新题。</p><div className="mt-6 grid gap-3 text-foreground sm:grid-cols-2 lg:grid-cols-4"><label className="space-y-2 text-xs text-emerald-100">卡组<select aria-label="卡组" className={selectClass} value={deckId} disabled={busy} onChange={e => { setDeckId(e.target.value); setEditing(null); }}><option value="">全部卡组</option>{decks.filter(d => !d.archived).map(d => <option key={d.id} value={d.id}>{d.title}</option>)}</select></label><label className="space-y-2 text-xs text-emerald-100">题型<select aria-label="题型" className={selectClass} value={kind} disabled={busy} onChange={e => setKind(e.target.value as StudyKind | "")}><option value="">全部题型</option>{Object.entries(kindLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label><label className="space-y-2 text-xs text-emerald-100">知识点<Input className="bg-background text-foreground" value={point} maxLength={120} disabled={busy} onChange={e => setPoint(e.target.value)} placeholder="全部知识点" /></label><label className="space-y-2 text-xs text-emerald-100">每轮题量<Input className="bg-background text-foreground" type="number" min={1} max={100} value={limit} disabled={busy} onChange={e => setLimit(Number(e.target.value))} /></label></div><div className="mt-6 flex flex-wrap gap-3"><Button className="bg-emerald-50 text-emerald-950 hover:bg-white" disabled={busy || !stats || limit < 1 || limit > 100} onClick={() => start("daily")}>开始复习<ArrowRight className="ml-3 h-4 w-4" /></Button><Button className="text-emerald-50 hover:bg-emerald-900 hover:text-white" variant="ghost" disabled={busy} onClick={() => start("mistakes")}>错题重练</Button></div></section>
            <section><div className="mb-4 flex items-center gap-2"><Target className="h-4 w-4 text-emerald-700" /><h3 className="font-medium">值得再练一次</h3></div>{stats?.weak_points.some(p => p.weak_count > 0) ? <div className="divide-y rounded-xl border">{stats.weak_points.filter(p => p.weak_count > 0).slice(0, 6).map(p => <div key={p.knowledge_point} className="flex flex-wrap items-center justify-between gap-3 p-4"><div><p className="text-sm font-medium">{p.knowledge_point}</p><p className="mt-1 text-xs text-muted-foreground">最近 {p.samples} 次中 {p.weak_count} 次忘记／困难 · {Math.round(p.ratio * 100)}%</p></div><Button variant="ghost" size="sm" disabled={busy} onClick={() => start("weak", p.knowledge_point)}>针对练习<ArrowRight className="ml-2 h-3 w-3" /></Button></div>)}</div> : <div className="rounded-xl border border-dashed p-8 text-center text-sm text-muted-foreground">完成练习后，这里会显示需要巩固的知识点。</div>}</section>
            <section><h3 className="mb-4 font-medium">近期练习</h3>{!stats?.sessions.length && <p className="text-sm text-muted-foreground">还没有练习记录。从生成一组题目开始。</p>}<div className="divide-y">{stats?.sessions.slice(0, 6).map(s => <button key={s.id} disabled={busy} onClick={() => void run(async () => updateRecord(await studyRequest<StudySession>(`/sessions/${s.id}`)))} className="flex w-full items-center justify-between gap-4 py-4 text-left text-sm hover:text-emerald-700"><span>{modes[s.mode]}<span className="ml-3 text-xs text-muted-foreground">{dateLabel(s.created_at)}</span></span><span className="shrink-0 text-xs">{s.confirmed}/{s.total} · {s.completed_at ? "查看复盘" : "继续练习"}</span></button>)}</div></section>
          </div>}
          <div hidden={tab !== "generate"}><Generator key={variant?.id || initialDocument || "new"} settings={modelSettings} documents={documents} decks={decks} initialDocument={initialDocument} variant={variant} busy={busy} run={job => void run(job)} onSaved={async id => { setDeckId(id); setItems(await studyRequest<StudyItem[]>(`/decks/${id}/items`)); await refresh(); setNotice("题目已保存，可以开始练习。"); setTab("decks"); }} /></div>
          {tab === "decks" && <section className="space-y-6"><div><p className="text-xs font-medium tracking-widest text-emerald-700 dark:text-emerald-400">LIBRARY / 卡组管理</p><h2 className="mt-3 text-3xl font-semibold">整理你的学习材料</h2></div>
            <form className="flex gap-3" onSubmit={e => { e.preventDefault(); void run(async () => { const deck = await studyRequest<StudyDeck>("/decks", "POST", { title: deckTitle }); setDeckTitle(""); await refresh(); setDeckId(deck.id); setNotice("卡组已创建，可前往生成题目。"); }); }}><Input required maxLength={120} aria-label="新卡组名称" placeholder="新卡组名称，例如：计算机网络" value={deckTitle} onChange={e => setDeckTitle(e.target.value)} /><Button disabled={busy || !deckTitle.trim()}><Plus className="mr-2 h-4 w-4" />创建卡组</Button></form>
            <label className="block space-y-2 text-sm">当前卡组<select aria-label="当前卡组" className={selectClass} value={deckId} onChange={e => { setDeckId(e.target.value); setItems([]); setEditing(null); setRename(""); }}><option value="">选择卡组</option>{decks.map(d => <option key={d.id} value={d.id}>{d.title}{d.archived ? "（已归档）" : ""}</option>)}</select></label>
            {selectedDeck && <><div className="flex flex-wrap items-center gap-3 rounded-xl bg-muted/40 p-4"><form className="flex flex-1 gap-2" onSubmit={e => { e.preventDefault(); void run(async () => { await studyRequest(`/decks/${deckId}`, "PATCH", { title: rename }); setRename(""); await refresh(); }); }}><Input aria-label="卡组新名称" placeholder={selectedDeck.title} value={rename} required maxLength={120} onChange={e => setRename(e.target.value)} /><Button variant="outline" disabled={busy || !rename.trim()}>重命名</Button></form><Button variant="ghost" disabled={busy} onClick={() => void run(async () => { await studyRequest(`/decks/${deckId}`, "PATCH", { archived: !selectedDeck.archived }); await refresh(); })}>{selectedDeck.archived ? "恢复卡组" : "归档卡组"}</Button></div><p className="text-xs text-muted-foreground">归档后停止排队，学习历史保留。</p>
              {items.length === 0 && <div className="rounded-xl border border-dashed p-8 text-center"><p className="mb-4 text-sm text-muted-foreground">卡组还是空的，为它添加第一组题目。</p><Button variant="outline" onClick={() => { setVariant(null); setTab("generate"); }}>生成题目</Button></div>}
              <div className="space-y-3">{items.map(item => <article key={item.id} className={`rounded-xl border p-5 ${item.archived ? "bg-muted/30" : "bg-card"}`}><div className="mb-2 flex flex-wrap justify-between gap-2 text-xs text-muted-foreground"><span>{kindLabels[item.kind]} · {item.knowledge_point}</span><span>{item.archived ? "已归档" : item.review_count ? `下次 ${dateLabel(item.due)}` : "新题"}</span></div>{editing?.id === item.id ? <form className="space-y-4" onSubmit={e => { e.preventDefault(); void run(async () => {
                const { kind, knowledge_point, prompt, answer, explanation, options, version } = editing;
                const updated = await studyRequest<StudyItem>(`/items/${item.id}`, "PATCH", { kind, knowledge_point, prompt, answer, explanation, options, version });
                setItems(prev => prev.map(i => i.id === updated.id ? updated : i)); setEditing(null); await refresh();
              }); }}><ItemEditor value={editing} onChange={content => setEditing({ ...editing, ...content })} /><p className="text-xs text-amber-700 dark:text-amber-400">修改题干、答案、题型或选项会重置此题复习进度；历史记录保留。</p><div className="flex gap-2"><Button disabled={busy}>保存修改</Button><Button type="button" variant="ghost" onClick={() => setEditing(null)}>取消</Button></div></form> : <><p className="whitespace-pre-wrap text-sm font-medium leading-relaxed">{item.prompt}</p><details className="mt-3 text-sm"><summary className="cursor-pointer text-muted-foreground">答案与来源</summary><p className="my-3 whitespace-pre-wrap">{item.answer}</p><p className="mb-3 whitespace-pre-wrap text-muted-foreground">{item.explanation}</p><SourceNote source={item.source} available={item.source_available} /></details><div className="mt-3 flex flex-wrap gap-2"><Button size="sm" variant="ghost" disabled={busy} onClick={() => setEditing(item)}>编辑</Button><Button size="sm" variant="ghost" disabled={busy} onClick={() => generateVariant(item.id)}>生成变式</Button><Button size="sm" variant="ghost" disabled={busy} onClick={() => void run(async () => { const updated = await studyRequest<StudyItem>(`/items/${item.id}/archive`, "POST", { archived: !item.archived, version: item.version }); setItems(prev => prev.map(i => i.id === updated.id ? updated : i)); await refresh(); })}>{item.archived ? "恢复" : "归档"}</Button></div></>}</article>)}</div>
            </>}
          </section>}
          {tab === "progress" && <section className="space-y-7"><div className="flex flex-wrap items-center justify-between gap-4"><div><p className="text-xs font-medium tracking-widest text-emerald-700 dark:text-emerald-400">REFLECT / 学习复盘</p><h2 className="mt-3 text-3xl font-semibold">看见积累，也看见盲点。</h2></div><select aria-label="统计时间范围" className={`${selectClass} max-w-36`} value={days} onChange={e => setDays(Number(e.target.value) as 7 | 30)}><option value={7}>最近 7 天</option><option value={30}>最近 30 天</option></select></div>
            <div className="grid gap-4 sm:grid-cols-3">{[["已确认练习", String(reviewed)], ["单选题正确率", choiceCount ? `${Math.round(correctCount / choiceCount * 100)}%（${correctCount}/${choiceCount}）` : "暂无记录"], ["闪记卡自评记得／轻松", flashCount ? `${flashRecalled}/${flashCount}` : "暂无记录"]].map(([label, value]) => <div key={label} className="rounded-xl border p-5"><p className="text-xs text-muted-foreground">{label}</p><p className="mt-3 text-xl font-medium tabular-nums">{value}</p></div>)}</div>
            <section className="rounded-2xl border p-6"><h3 className="mb-6 text-sm font-medium">每日练习次数</h3><div className="flex h-40 items-end gap-1 sm:gap-2" role="img" aria-label={trend.map(d => `${d.date}：${d.reviewed} 次`).join("，")}>{trend.map(d => <div key={d.date} className="group flex h-full min-w-0 flex-1 flex-col justify-end" title={`${d.date}：${d.reviewed} 次`}><div className="min-h-1 rounded-t bg-emerald-700/80 group-hover:bg-emerald-600" style={{ height: `${d.reviewed / maxDaily * 100}%` }} /></div>)}</div><div className="mt-3 flex justify-between text-xs text-muted-foreground"><span>{trend[0]?.date}</span><span>{trend.at(-1)?.date}</span></div><details className="mt-4 text-xs"><summary className="cursor-pointer text-muted-foreground">查看每日明细</summary><div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">{trend.map(d => <p key={d.date}>{d.date} · {d.reviewed} 次</p>)}</div></details></section>
            <section><h3 className="mb-4 font-medium">未来 7 天 · 已安排复习</h3><p className="mb-3 text-xs text-muted-foreground">按当前计划统计，不含新题及已逾期题目；每次确认后更新。</p><div className="grid grid-cols-4 gap-2 sm:grid-cols-7">{stats?.upcoming.map(d => <div key={d.date} className="rounded-xl border p-3 text-center"><p className="text-xs text-muted-foreground">{d.date.slice(5)}</p><p className="mt-2 text-xl tabular-nums">{d.count}</p></div>)}</div></section>
            <section><h3 className="mb-3 font-medium">知识点表现</h3><p className="mb-4 text-xs text-muted-foreground">每个知识点取最近 10 次确认记录；样本较少时仅供参考。</p><div className="divide-y">{stats?.weak_points.map(p => <div key={p.knowledge_point} className="flex flex-wrap justify-between gap-3 py-3 text-sm"><span>{p.knowledge_point}</span><span className="text-muted-foreground">忘记／困难 {p.weak_count}/{p.samples} · {Math.round(p.ratio * 100)}%</span></div>)}</div></section>
            <section><h3 className="mb-3 font-medium">练习与复盘记录</h3>{stats?.sessions.map(s => <button key={s.id} disabled={busy} onClick={() => void run(async () => updateRecord(await studyRequest<StudySession>(`/sessions/${s.id}`)))} className="flex w-full justify-between gap-3 border-b py-4 text-left text-sm"><span>{modes[s.mode]} · {dateLabel(s.created_at)}</span><span className="text-muted-foreground">{s.confirmed}/{s.total} · {s.completed_at ? "查看复盘" : "继续练习"}</span></button>)}</section>
          </section>}
        </>}
      </div>
    </main>
  </div>;
}
