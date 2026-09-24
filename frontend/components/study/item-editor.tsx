"use client";

import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { API_BASE_URL } from "@/lib/api";
import { ItemContent, kindLabels, StudyKind, StudySource } from "@/lib/study-api";

export const selectClass = "h-10 w-full rounded-md border border-input bg-background px-3 text-sm text-foreground focus-visible:outline-2 focus-visible:outline-ring";

export function SourceNote({ source, available = true }: { source: StudySource; available?: boolean }) {
  if (source.mode === "topic") return <p className="text-xs text-amber-700 dark:text-amber-400">模型生成，未经资料核验 · {source.title}</p>;
  return <details className="rounded-lg border border-border bg-muted/30 px-4 py-3 text-sm">
    <summary className="cursor-pointer text-muted-foreground">原文依据 · {source.title}{source.chunk_index !== null ? ` · 第 ${source.chunk_index + 1} 块` : ""}</summary>
    <blockquote className="mt-3 whitespace-pre-wrap border-l-2 border-emerald-500 pl-3 leading-relaxed">{source.excerpt}</blockquote>
    {source.mode === "document" && (available ? <a className="mt-3 inline-block underline underline-offset-4" href={`${API_BASE_URL}/api/documents/${source.document_id}/file`} target="_blank" rel="noreferrer">打开原文档</a> : <p className="mt-3 text-muted-foreground">原文档已删除，摘录仍可使用</p>)}
  </details>;
}

export function ItemEditor({ value, onChange }: { value: ItemContent; onChange: (value: ItemContent) => void }) {
  const set = (patch: Partial<ItemContent>) => onChange({ ...value, ...patch });
  return <div className="space-y-4">
    <div className="grid gap-4 sm:grid-cols-2">
      <label className="space-y-2 text-sm">题型<select aria-label="题型" className={selectClass} value={value.kind} onChange={e => set({ kind: e.target.value as StudyKind, options: e.target.value === "choice" ? ["", "", "", ""] : [] })}>
        {Object.entries(kindLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
      </select></label>
      <label className="space-y-2 text-sm">知识点<Input required maxLength={120} value={value.knowledge_point} onChange={e => set({ knowledge_point: e.target.value })} /></label>
    </div>
    <label className="block space-y-2 text-sm">题干<Textarea aria-label="题干" required maxLength={4000} value={value.prompt} onChange={e => set({ prompt: e.target.value })} /></label>
    {value.kind === "choice" && <div className="grid gap-3 sm:grid-cols-2">{value.options.map((option, index) => <label key={index} className="space-y-2 text-sm">选项 {String.fromCharCode(65 + index)}<Input required maxLength={1000} value={option} onChange={e => set({ options: value.options.map((o, i) => i === index ? e.target.value : o) })} /></label>)}</div>}
    <label className="block space-y-2 text-sm">{value.kind === "choice" ? "正确答案（与一个选项完全一致）" : "参考答案"}<Textarea aria-label={value.kind === "choice" ? "正确答案" : "参考答案"} required maxLength={4000} value={value.answer} onChange={e => set({ answer: e.target.value })} /></label>
    <label className="block space-y-2 text-sm">解析<Textarea aria-label="解析" required maxLength={6000} value={value.explanation} onChange={e => set({ explanation: e.target.value })} /></label>
  </div>;
}
