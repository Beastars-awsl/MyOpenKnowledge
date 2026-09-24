"use client";

import { useRef, useState } from "react";
import { ArrowLeft, Check, RotateCcw, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { SourceNote } from "@/components/study/item-editor";
import { kindLabels, ModelSettings, ratingLabels, StudyAttempt, StudySession, studyRequest } from "@/lib/study-api";

export function dateLabel(value: string) { return new Date(value).toLocaleString("zh-CN", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }); }

function Question({ attempt, busy, submit, confirm }: { attempt: StudyAttempt; busy: boolean; submit: (answer: string) => void; confirm: (rating: number) => void }) {
  const [answer, setAnswer] = useState("");
  const question = attempt.question;
  return <article className="overflow-hidden rounded-2xl border bg-card">
    <div className="border-b bg-muted/30 px-6 py-4 text-xs font-medium tracking-wide text-muted-foreground">{kindLabels[question.kind]} <span className="mx-2">/</span> {question.knowledge_point}</div>
    <div className="space-y-6 p-6 sm:p-10">
      <h2 className="whitespace-pre-wrap text-xl font-medium leading-relaxed sm:text-2xl">{question.prompt}</h2>
      {!attempt.feedback ? <form onSubmit={e => { e.preventDefault(); submit(answer); }}><fieldset disabled={busy} className="space-y-5">
        {question.kind === "choice" && <fieldset className="space-y-3"><legend className="sr-only">选择答案</legend>{question.options.map((option, i) => <label key={i} className={`flex cursor-pointer items-start gap-3 rounded-xl border p-4 transition-colors ${answer === option ? "border-emerald-600 bg-emerald-50 dark:bg-emerald-950/30" : "hover:bg-muted/50"}`}><input required className="mt-1 accent-emerald-700" type="radio" name={`answer-${attempt.id}`} checked={answer === option} value={option} onChange={() => setAnswer(option)} /><span className="leading-relaxed"><span className="mr-3 text-muted-foreground">{String.fromCharCode(65 + i)}.</span>{option}</span></label>)}</fieldset>}
        {question.kind === "short_answer" && <label className="block space-y-2 text-sm">你的回答<Textarea required rows={6} maxLength={8000} value={answer} onChange={e => setAnswer(e.target.value)} placeholder="先用自己的话回答，再查看解析。" /></label>}
        {question.kind === "flashcard" && <p className="py-8 text-center text-muted-foreground">停一下，试着在脑海中完整回答。</p>}
        <Button type="submit" disabled={busy}>{busy ? "处理中…" : question.kind === "flashcard" ? "翻开答案" : "提交答案"}</Button>
      </fieldset></form> : <div className="space-y-5">
        {attempt.answer && <div className="rounded-xl bg-muted/40 p-4"><p className="mb-2 text-xs text-muted-foreground">你的回答</p><p className="whitespace-pre-wrap">{attempt.answer}</p></div>}
        <div className="border-l-2 border-emerald-600 pl-5"><p className="mb-2 text-xs font-medium text-emerald-700 dark:text-emerald-400">参考答案</p><p className="whitespace-pre-wrap leading-relaxed">{question.answer}</p><p className="mt-4 whitespace-pre-wrap text-sm leading-relaxed text-muted-foreground">{question.explanation}</p></div>
        <div className="rounded-xl bg-muted/40 p-4 text-sm"><p className="whitespace-pre-wrap font-medium">{attempt.feedback.summary}</p>{attempt.feedback.omissions.length > 0 && <p className="mt-2">遗漏：{attempt.feedback.omissions.join("；")}</p>}{attempt.feedback.misconceptions.length > 0 && <p className="mt-2">误区：{attempt.feedback.misconceptions.join("；")}</p>}</div>
        {question.source && <SourceNote source={question.source} available={attempt.source_available} />}
        <div className="border-t pt-6"><p className="mb-4 text-sm">确认刚才的掌握情况<span className="ml-2 text-muted-foreground">{!attempt.feedback.unavailable && `建议：${ratingLabels[attempt.feedback.suggested_rating - 1]}`} · 由你决定</span></p><div className="grid grid-cols-2 gap-3 sm:grid-cols-4">{ratingLabels.map((label, index) => <button key={label} disabled={busy} onClick={() => confirm(index + 1)} className={`rounded-xl border px-2 py-4 text-center transition-colors hover:border-emerald-600 hover:bg-emerald-50 focus-visible:outline-2 focus-visible:outline-emerald-600 disabled:opacity-40 dark:hover:bg-emerald-950/40 ${index === 2 ? "border-emerald-600" : "border-border"}`}><span className="block font-medium">{label}</span><span className="mt-2 block text-xs text-muted-foreground">{attempt.intervals[String(index + 1)] ? dateLabel(attempt.intervals[String(index + 1)]) : "确认后安排"}</span></button>)}</div><p className="mt-3 text-xs text-muted-foreground">下次复习时间按实际确认时刻计算。只有确认后才计入学习记录。</p></div>
      </div>}
    </div>
  </article>;
}

export function Practice({ record, settings, busy, run, onChange, onExit, onVariant }: {
  record: StudySession; settings: ModelSettings; busy: boolean; run: (job: () => Promise<void>) => void;
  onChange: (record: StudySession) => Promise<void>; onExit: () => void; onVariant: (itemId: string) => void;
}) {
  const confirmation = useRef<{ attempt: string; rating: number; id: string } | null>(null);
  const current = record.attempts.find(a => a.rating === null && !a.unavailable);
  const confirmed = record.attempts.filter(a => a.rating !== null);
  const choices = confirmed.filter(a => a.objective_correct !== null);
  const cards = confirmed.filter(a => a.question.kind === "flashcard");
  const complete = !!record.completed_at;
  const reload = async () => onChange(await studyRequest<StudySession>(`/sessions/${record.id}`));
  return <div className="mx-auto max-w-3xl space-y-6">
    <div className="flex flex-wrap items-center justify-between gap-3"><Button variant="ghost" disabled={busy} onClick={onExit}><ArrowLeft className="mr-2 h-4 w-4" />{complete ? "返回学习首页" : "退出，稍后继续"}</Button><div className="flex gap-2"><Button variant="ghost" disabled={busy} onClick={() => run(reload)}><RotateCcw className="mr-2 h-4 w-4" />刷新进度</Button>{!complete && <Button variant="outline" disabled={busy} onClick={() => run(async () => onChange(await studyRequest<StudySession>(`/sessions/${record.id}/finish`, "POST")))}>结束并复盘</Button>}</div></div>
    <div><div className="mb-2 flex justify-between text-sm"><span>{complete ? "本轮已结束" : "专注这一题"}</span><span>{confirmed.length} / {record.attempts.length} 已确认</span></div><progress className="h-1.5 w-full accent-emerald-700" max={record.attempts.length} value={confirmed.length} aria-label="本轮进度" /></div>
    {!complete && current ? <Question key={current.id} attempt={current} busy={busy} submit={answer => run(async () => {
      await studyRequest(`/attempts/${current.id}/answer`, "POST", { ...settings, answer });
      await reload();
    })} confirm={rating => run(async () => {
      if (!confirmation.current || confirmation.current.attempt !== current.id || confirmation.current.rating !== rating) confirmation.current = { attempt: current.id, rating, id: crypto.randomUUID() };
      await studyRequest(`/attempts/${current.id}/confirm`, "POST", { rating, version: current.item_version, confirmation_id: confirmation.current.id });
      await reload();
      confirmation.current = null;
    })} /> : <section className="space-y-6">
      {!complete && <p className="rounded-xl border p-4 text-sm">剩余题目已发生变化或被归档，请点击“结束并复盘”，再开始新一轮。</p>}
      <div className="rounded-2xl border bg-card p-6 sm:p-8"><Check className="mb-4 h-7 w-7 text-emerald-700" /><h2 className="text-2xl font-semibold">让每次练习，都留下收获。</h2><p className="mt-2 text-sm text-muted-foreground">已确认 {confirmed.length} 题 · 未完成 {record.attempts.length - confirmed.length} 题不计入统计</p><div className="mt-6 grid grid-cols-2 gap-6"><div><p className="text-xs text-muted-foreground">单选题正确</p><p className="mt-2 text-2xl tabular-nums">{choices.filter(a => a.objective_correct).length}<span className="text-sm text-muted-foreground"> / {choices.length}</span></p></div><div><p className="text-xs text-muted-foreground">闪记卡自评记得／轻松</p><p className="mt-2 text-2xl tabular-nums">{cards.filter(a => (a.rating || 0) >= 3).length}<span className="text-sm text-muted-foreground"> / {cards.length}</span></p></div></div></div>
      <div className="rounded-2xl border p-6"><div className="flex flex-wrap items-center justify-between gap-3"><h3 className="font-medium">AI 学习复盘</h3><Button variant="outline" disabled={busy || !complete || !confirmed.length || !!record.recap} onClick={() => run(async () => onChange(await studyRequest<StudySession>(`/sessions/${record.id}/recap`, "POST", settings)))}><Sparkles className="mr-2 h-4 w-4" />{record.recap ? "已保存" : "生成本轮复盘"}</Button></div>{record.recap ? <p className="mt-4 whitespace-pre-wrap text-sm leading-7">{record.recap}</p> : <p className="mt-3 text-sm text-muted-foreground">按需分析真实作答记录，给出具体的知识缺口与学习建议。</p>}</div>
    </section>}
    {confirmed.length > 0 && <details open={complete} className="rounded-2xl border p-6"><summary className="cursor-pointer font-medium">本轮已确认记录 · {confirmed.length} 题</summary><div className="mt-4 divide-y">{confirmed.map(attempt => <div className="space-y-2 py-4" key={attempt.id}><div className="flex flex-wrap justify-between gap-2 text-xs text-muted-foreground"><span>{kindLabels[attempt.question.kind]} · {attempt.question.knowledge_point}</span><span>{ratingLabels[(attempt.rating || 1) - 1]}{attempt.objective_correct !== null && (attempt.objective_correct ? " · 答对" : " · 答错")}</span></div><p className="text-sm font-medium">{attempt.question.prompt}</p><details className="text-sm"><summary className="cursor-pointer text-muted-foreground">查看答案与点评</summary><div className="mt-3 space-y-3"><p className="whitespace-pre-wrap">你的回答：{attempt.answer || "翻卡自评"}</p><p className="whitespace-pre-wrap">参考答案：{attempt.question.answer}</p><p className="whitespace-pre-wrap text-muted-foreground">{attempt.question.explanation}</p><p>{attempt.feedback?.summary}</p>{attempt.question.source && <SourceNote source={attempt.question.source} available={attempt.source_available} />}</div></details><div className="flex flex-wrap items-center justify-between gap-2"><p className="text-xs text-muted-foreground">当次安排：{attempt.next_due && dateLabel(attempt.next_due)}</p><Button size="sm" variant="ghost" disabled={busy} onClick={() => onVariant(attempt.item_id)}><Sparkles className="mr-1 h-3 w-3" />生成变式</Button></div></div>)}</div></details>}
  </div>;
}
