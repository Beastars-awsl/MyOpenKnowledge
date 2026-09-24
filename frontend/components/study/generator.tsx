"use client";

import { useState } from "react";
import { Sparkles, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { ItemEditor, selectClass, SourceNote } from "@/components/study/item-editor";
import { GenerateInput, ItemDraft, kindLabels, ModelSettings, StudyDeck, StudyDocument, StudyItem, StudyKind, StudySource, studyRequest } from "@/lib/study-api";

interface Props {
  settings: ModelSettings; documents: StudyDocument[]; decks: StudyDeck[]; initialDocument: string;
  variant: StudyItem | null; busy: boolean; run: (job: () => Promise<void>) => void;
  onSaved: (deck: string) => Promise<void>;
}

export function Generator({ settings, documents, decks, initialDocument, variant, busy, run, onSaved }: Props) {
  const [mode, setMode] = useState<StudySource["mode"]>(initialDocument ? "document" : "text");
  const [documentId, setDocumentId] = useState(initialDocument);
  const [text, setText] = useState("");
  const [focus, setFocus] = useState("");
  const [count, setCount] = useState(10);
  const [start, setStart] = useState(1);
  const [chunkCount, setChunkCount] = useState(8);
  const [kinds, setKinds] = useState<StudyKind[]>(["flashcard", "choice", "short_answer"]);
  const [preview, setPreview] = useState<(ItemDraft & { id: string; selected: boolean })[]>([]);
  const [coverage, setCoverage] = useState("");
  const [deckId, setDeckId] = useState(variant?.deck_id || decks.find(d => !d.archived)?.id || "");

  function generate() {
    run(async () => {
      const request: GenerateInput = { ...settings, mode, document_id: documentId || null, text, focus,
        count, kinds, start_chunk: start - 1, chunk_count: chunkCount, variant_item_id: variant?.id || null };
      const result = await studyRequest<{ items: ItemDraft[]; coverage: string }>("/generate", "POST", request);
      setPreview(result.items.map(item => ({ ...item, id: crypto.randomUUID(), selected: true })));
      setCoverage(result.coverage);
    });
  }

  return <div className="space-y-8">
    <div><p className="text-xs font-medium tracking-widest text-emerald-700 dark:text-emerald-400">CREATE / 创建学习材料</p><h2 className="mt-2 text-2xl font-semibold">{variant ? `围绕「${variant.knowledge_point}」举一反三` : "把知识，变成可以练习的问题。"}</h2><p className="mt-2 text-sm text-muted-foreground">先检查、再保存。只有你确认的题目会进入复习计划。</p></div>
    <form onSubmit={e => { e.preventDefault(); generate(); }} className="rounded-2xl border bg-card p-5 sm:p-7">
      <fieldset disabled={busy} className="space-y-5">
        {variant ? <div className="space-y-3"><p className="text-sm">原题：{variant.prompt}</p><SourceNote source={variant.source} available={variant.source_available} /></div> : <>
          <label className="block space-y-2 text-sm">内容来源<select aria-label="内容来源" className={selectClass} value={mode} onChange={e => setMode(e.target.value as StudySource["mode"])}><option value="text">粘贴文本</option><option value="document">知识库文档</option><option value="topic">自由主题</option></select></label>
          {mode === "document" ? <div className="space-y-4">
            <label className="block space-y-2 text-sm">选择文档<select aria-label="选择文档" required className={selectClass} value={documentId} onChange={e => setDocumentId(e.target.value)}><option value="">请选择已处理完成的文档</option>{documents.filter(d => d.status === "completed").map(d => <option key={d.id} value={d.id}>{d.title}</option>)}</select></label>
            <div className="grid gap-4 sm:grid-cols-2"><label className="space-y-2 text-sm">起始分块（从 1 开始）<Input type="number" required min={1} value={start} onChange={e => setStart(Number(e.target.value))} /></label><label className="space-y-2 text-sm">本次分块数量<Input type="number" required min={1} max={12} value={chunkCount} onChange={e => setChunkCount(Number(e.target.value))} /></label></div>
            <p className="text-xs text-muted-foreground">每次最多 12 块、16000 字；生成后显示实际范围。可更换起始分块继续学习。</p>
          </div> : <label className="block space-y-2 text-sm">{mode === "text" ? "学习资料" : "学习主题"}<Textarea required maxLength={16000} rows={6} value={text} onChange={e => setText(e.target.value)} placeholder={mode === "text" ? "粘贴笔记、教材片段或整理好的知识……" : "例如：Python 异步编程中的事件循环与协程"} /></label>}
          {mode === "topic" && <p className="text-xs text-amber-700 dark:text-amber-400">自由主题由模型生成，未经资料核验，请在保存前核对。</p>}
        </>}
        <div className="grid gap-4 sm:grid-cols-[1fr_120px]"><label className="space-y-2 text-sm">学习重点（可选）<Input maxLength={1000} value={focus} onChange={e => setFocus(e.target.value)} placeholder="例如：概念辨析、实际应用、易错点" /></label><label className="space-y-2 text-sm">生成数量<Input type="number" required min={1} max={20} value={count} onChange={e => setCount(Number(e.target.value))} /></label></div>
        <fieldset><legend className="mb-3 text-sm">题型（至少选择一种）</legend><div className="flex flex-wrap gap-4">{Object.entries(kindLabels).map(([key, label]) => <label key={key} className="flex items-center gap-2 text-sm"><input type="checkbox" className="h-4 w-4 accent-emerald-700" checked={kinds.includes(key as StudyKind)} onChange={e => setKinds(e.target.checked ? [...kinds, key as StudyKind] : kinds.filter(k => k !== key))} />{label}</label>)}</div></fieldset>
        <Button type="submit" disabled={busy || !kinds.length}><Sparkles className="mr-2 h-4 w-4" />{busy ? "处理中…" : preview.length ? "重新生成预览" : "生成预览"}</Button>
      </fieldset>
    </form>
    {preview.length > 0 && <section className="space-y-4">
      <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-100"><p>{coverage}</p><p className="mt-1">预览尚未保存，刷新页面会丢失。展开题目可编辑。</p></div>
      {preview.map((item, index) => <article key={item.id} className="rounded-xl border bg-card p-5"><div className="mb-3 flex items-center gap-3"><input aria-label={`保存第 ${index + 1} 题`} type="checkbox" className="h-4 w-4 accent-emerald-700" checked={item.selected} disabled={busy} onChange={e => setPreview(prev => prev.map(p => p.id === item.id ? { ...p, selected: e.target.checked } : p))} /><span className="text-xs text-muted-foreground">{String(index + 1).padStart(2, "0")} / {kindLabels[item.kind]} · {item.knowledge_point}</span></div><details><summary className="cursor-pointer font-medium leading-relaxed">{item.prompt}</summary><fieldset disabled={busy} className="mt-5"><ItemEditor value={item} onChange={value => setPreview(prev => prev.map(p => p.id === item.id ? { ...p, ...value } : p))} /></fieldset></details><div className="mt-4"><SourceNote source={item.source} /></div></article>)}
      <div className="flex flex-wrap items-end gap-3 rounded-xl border bg-card p-5"><label className="min-w-48 flex-1 space-y-2 text-sm">保存到卡组<select aria-label="保存到卡组" className={selectClass} value={deckId} onChange={e => setDeckId(e.target.value)}><option value="">请选择卡组</option>{decks.filter(d => !d.archived).map(d => <option key={d.id} value={d.id}>{d.title}</option>)}</select></label><Button disabled={busy || !deckId || !preview.some(p => p.selected)} onClick={() => run(async () => {
        const items = preview.filter(p => p.selected).map(({ selected, ...item }) => { void selected; return item; });
        await studyRequest(`/decks/${deckId}/items`, "POST", { items });
        setPreview([]);
        await onSaved(deckId);
      })}><Check className="mr-2 h-4 w-4" />保存所选 {preview.filter(p => p.selected).length} 题</Button></div>
      {!decks.some(d => !d.archived) && <p className="text-sm text-amber-700">请先在“卡组管理”创建一个卡组，再回来保存预览。</p>}
    </section>}
  </div>;
}
