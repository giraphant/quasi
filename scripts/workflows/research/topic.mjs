import {
  CARD_PROBE_SCHEMA,
  CARD_SCHEMA,
  PROBE_SCHEMA,
  RECALL_SCHEMA,
  cardExistencePrompt,
  existsProbePrompt,
  vaultRecallPrompt,
  webcardPrompt,
} from "../operations/acquire.mjs";
import { AU_SCHEMA } from "../operations/audit.mjs";
import {
  SY_SCHEMA,
  topicDossierSynthPrompt,
  topicSpineSynthPrompt,
} from "../operations/synthesise.mjs";
import {
  STEER_SCHEMA,
  cardPath,
  mergeCards,
  mergeItems,
  pendingCards,
  registered,
  steerPrompt,
} from "../operations/steer.mjs";
import { OVERWRITE } from "../runtime.mjs";
import { processTopicStrict } from "./topic-recall.mjs";

export const positiveInt = (value, fallback) => {
  const parsed = Math.floor(Number(value));
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
};

export async function processTopicLegacy(runtime, router, slug, meta) {
  const { guard, log, parallel, phase, retryNull } = runtime;
  phase("Recall");
  const desc = meta.desc || meta.topic_desc || slug;
  const maxRounds = positiveInt(meta.maxRounds, 3);
  const perRound = positiveInt(meta.maxPerRound, 8);
  const perCards = positiveInt(meta.maxCardsPerRound, 3);

  const [recall, initialSteer] = await parallel([
    () =>
      retryNull(vaultRecallPrompt(desc, perRound * 2), {
        phase: "Recall",
        agentType: "general-purpose",
        label: `${slug}:recall`,
        schema: RECALL_SCHEMA,
      }),
    () =>
      retryNull(
        steerPrompt(slug, desc, 0, [], [], perRound, meta.seeds),
        {
          phase: "Search",
          agentType: "quasi:steer-agent",
          label: `${slug}:steer:r0`,
          schema: STEER_SCHEMA,
        },
      ),
  ]);
  let steer = initialSteer || { subquestions: [] };
  const local = ((recall && recall.items) || [])
    .filter((item) => item && item.slug)
    .map((item) => ({
      kind:
        item.kind === "book" || item.kind === "talk"
          ? item.kind
          : "paper",
      slug: item.slug,
    }));
  let queue = (steer.candidates || []).filter(
    (candidate) => candidate && candidate.slug,
  );
  const cards = [];
  const cardSlugs = new Set();
  const cardAttempts = new Set();
  const availableCards = new Set();
  const scheduleCards = (state) => {
    const pending = pendingCards(state, [...cardAttempts], perCards);
    if (pending.dropped)
      log(
        `${slug}: 卡任务按每轮上限 ${perCards} 截去 ${pending.dropped} 条`,
      );
    return pending.tasks;
  };
  let webTasks = scheduleCards(steer);
  const priorCards = registered(steer);
  const priorProbe = priorCards.length
    ? await retryNull(cardExistencePrompt(slug, priorCards), {
        phase: "Recall",
        agentType: "general-purpose",
        label: `${slug}:probe-cards:r0`,
        schema: CARD_PROBE_SCHEMA,
      })
    : null;
  ((priorProbe && priorProbe.existing) || [])
    .filter((card) => priorCards.includes(card))
    .forEach((card) => availableCards.add(card));
  if (
    !queue.length &&
    !local.length &&
    !webTasks.length &&
    !availableCards.size
  )
    return { slug, status: "no_works" };

  const seen = new Set(local.map((item) => item.slug));
  const ok = [...local];
  const failures = [];
  const dirty = new Set(
    (initialSteer && initialSteer.dirty) || [],
  );
  let round = 0;
  let suggested =
    (initialSteer && initialSteer.suggested_queries) || null;
  let saturated = !!(initialSteer && initialSteer.saturated);
  let steerReceipts = initialSteer ? 1 : 0;
  const isBook = (candidate) =>
    (candidate.kind || "paper") === "book";

  while (
    (queue.length || webTasks.length) &&
    round < maxRounds &&
    !saturated
  ) {
    round++;
    const batch = queue
      .filter((candidate) => !seen.has(candidate.slug))
      .slice(0, perRound);
    batch.forEach((candidate) => seen.add(candidate.slug));
    const roundTasks = webTasks;
    if (!batch.length && !roundTasks.length) break;
    roundTasks.forEach((task) => cardAttempts.add(task.card_slug));
    const cardWork = parallel(
      roundTasks.map(
        (task) => () =>
          retryNull(webcardPrompt(slug, desc, task, steer), {
            phase: "Search",
            agentType: "quasi:webcard-agent",
            label: `${slug}:webcard:${task.card_slug}`,
            schema: CARD_SCHEMA,
          }),
      ),
    );

    const probe = batch.length
      ? await retryNull(
          existsProbePrompt(
            batch.filter(isBook),
            batch.filter((candidate) => !isBook(candidate)),
          ),
          {
            phase: "Recall",
            agentType: "general-purpose",
            label: `${slug}:probe-done:r${round}`,
            schema: PROBE_SCHEMA,
          },
        )
      : null;
    const done = new Map(
      ((probe && probe.resolved) || [])
        .filter(
          (item) => item && item.slug && item.vault_slug,
        )
        .map((item) => [item.slug, item.vault_slug]),
    );

    const fresh = batch
      .filter((candidate) => !done.has(candidate.slug))
      .filter(
        (candidate) =>
          meta.allowAuthors ||
          (candidate.kind || "paper") !== "author",
      );
    const results = (
      await parallel(
        fresh.map(
          (candidate) => () => {
            const kind = isBook(candidate)
              ? "book"
              : candidate.kind === "author"
                ? "author"
                : "paper";
            return router(
              kind,
              {
                slug: candidate.slug,
                name: candidate.slug,
                meta: { ...candidate, topic: slug },
              },
              { batchYear: true },
            ).then((result) => ({
              kind,
              slug: candidate.slug,
              ...result,
            }));
          },
        ),
      )
    ).filter(Boolean);

    const roundOk = [
      ...batch
        .filter((candidate) => done.has(candidate.slug))
        .map((candidate) => ({
          kind: isBook(candidate) ? "book" : "paper",
          slug: done.get(candidate.slug),
          subq: candidate.subq,
          role: candidate.role,
        })),
      ...results
        .filter((result) => result.status === "ok")
        .map((result) => {
          const candidate =
            batch.find(
              (item) => item.slug === result.slug,
            ) || {};
          return {
            kind: result.kind,
            slug: result.slug,
            subq: candidate.subq,
            role: candidate.role,
          };
        }),
    ].filter(
      (item) => !ok.some((existing) => existing.slug === item.slug),
    );
    ok.push(...roundOk);
    roundOk.forEach(
      (item) => item.subq && dirty.add(item.subq),
    );
    failures.push(
      ...results
        .filter((result) => result.status !== "ok")
        .map((result) => ({
          slug: result.slug,
          status: result.status,
        })),
    );

    const cardResults = await cardWork;
    const claims = roundTasks.map((task, index) => {
      const receipt = cardResults[index];
      const expected = cardPath(slug, task.card_slug);
      const identityOk =
        receipt &&
        receipt.card_path === expected &&
        receipt.subq === task.subq;
      return {
        ...task,
        expected,
        receipt,
        status: identityOk
          ? receipt.status
          : receipt
            ? "invalid_receipt"
            : "agent_failed",
      };
    });
    const claimedFiles = claims.filter(
      (claim) =>
        claim.status === "ok" || claim.status === "unchanged",
    );
    const cardProbe = claimedFiles.length
      ? await retryNull(
          cardExistencePrompt(
            slug,
            claimedFiles.map((claim) => claim.card_slug),
          ),
          {
            phase: "Recall",
            agentType: "general-purpose",
            label: `${slug}:probe-cards:r${round}`,
            schema: CARD_PROBE_SCHEMA,
          },
        )
      : null;
    const present = new Set(
      ((cardProbe && cardProbe.existing) || []).filter((card) =>
        claimedFiles.some((claim) => claim.card_slug === card),
      ),
    );
    const roundCards = claimedFiles
      .filter((claim) => present.has(claim.card_slug))
      .map((claim) => ({
        subq: claim.subq,
        card_slug: claim.card_slug,
        query: claim.query,
        note: claim.note,
        title:
          (claim.receipt && claim.receipt.title) ||
          claim.card_slug,
        status: claim.status,
      }));
    roundCards.forEach((card) => {
      cards.push(card);
      cardSlugs.add(card.card_slug);
      availableCards.add(card.card_slug);
    });
    roundCards
      .filter((card) => card.status === "ok")
      .forEach((card) => card.subq && dirty.add(card.subq));
    const accepted = new Set(
      roundCards.map((card) => card.card_slug),
    );
    claims
      .filter((claim) => !accepted.has(claim.card_slug))
      .forEach((claim) =>
        failures.push({
          kind: "card",
          slug: claim.card_slug,
          status:
            claim.status === "ok" ||
            claim.status === "unchanged"
              ? "missing"
              : claim.status,
        }),
      );

    const snowSource =
      round === 1 ? [...local, ...roundOk] : roundOk;
    const nextSteer = await retryNull(
      steerPrompt(
        slug,
        desc,
        round,
        snowSource,
        [...seen],
        perRound,
        null,
        roundCards,
      ),
      {
        phase: "Search",
        agentType: "quasi:steer-agent",
        label: `${slug}:steer:r${round}`,
        schema: STEER_SCHEMA,
      },
    );
    if (nextSteer) {
      steer = nextSteer;
      steerReceipts++;
    }
    (steer.dirty || []).forEach((entry) => dirty.add(entry));
    queue = (steer.candidates || []).filter(
      (candidate) =>
        candidate &&
        candidate.slug &&
        !seen.has(candidate.slug),
    );
    webTasks = nextSteer ? scheduleCards(steer) : [];
    saturated = !!steer.saturated;
    suggested = steer.suggested_queries || null;
    log(
      `${slug}: 第 ${round} 轮 +${roundOk.length} 条 +${roundCards.length} 卡` +
        `(累计 ${ok.length} 条 / ${cards.length} 卡),下轮候选 ${queue.length} + ${webTasks.length} 卡任务` +
        (saturated ? ";掌舵判饱和,收口" : ""),
    );
  }

  if (round === 0 && local.length) {
    const closingSteer = await retryNull(
      steerPrompt(
        slug,
        desc,
        1,
        local,
        [...seen],
        perRound,
        null,
        [],
      ),
      {
        phase: "Search",
        agentType: "quasi:steer-agent",
        label: `${slug}:steer:r1-close`,
        schema: STEER_SCHEMA,
      },
    );
    if (closingSteer) {
      steer = closingSteer;
      steerReceipts++;
      round = 1;
      (closingSteer.dirty || []).forEach((entry) =>
        dirty.add(entry),
      );
      suggested =
        closingSteer.suggested_queries || suggested;
      saturated = !!closingSteer.saturated;
    }
  }

  const minItems = positiveInt(meta.minItems, 3);
  const liveRegistered = registered(steer).filter((card) =>
    availableCards.has(card),
  );
  const cardCount = new Set([
    ...liveRegistered,
    ...cardSlugs,
  ]).size;
  const evidence = ok.length + cardCount;
  if (
    !meta.final &&
    !queue.length &&
    !webTasks.length &&
    evidence < minItems
  )
    return {
      slug,
      status: "needs_seeds",
      collected: ok.length,
      cards: cardCount,
      rounds: round,
      suggested_queries: suggested,
      failures: failures.length,
    };
  if (!evidence)
    return {
      slug,
      status: "all_failed",
      tried: failures.length,
    };

  const persistedSubquestions = (steer.subquestions || [])
    .filter((subquestion) => subquestion && subquestion.id)
    .map((subquestion) => ({
      ...subquestion,
      cards: (subquestion.cards || []).filter((card) =>
        availableCards.has(card),
      ),
    }));
  const subquestions = mergeCards(
    mergeItems(persistedSubquestions, ok),
    cards,
  );
  const dossiers = subquestions.filter(
    (subquestion) => subquestion.dossier && subquestion.page,
  );
  const dirtyDossiers = dossiers.filter((subquestion) =>
    steerReceipts ? dirty.has(subquestion.id) : true,
  );
  const dossierResults = await parallel(
    dirtyDossiers.map(
      (subquestion) => () =>
        retryNull(
          topicDossierSynthPrompt(
            slug,
            desc,
            subquestion,
            cards,
          ),
          {
            phase: "Synthesise",
            agentType: "quasi:synthesis-agent",
            label: `${slug}:synthesise-dossier:${subquestion.id}`,
            schema: SY_SCHEMA,
          },
          OVERWRITE,
        ),
    ),
  );
  const dossiersFailed = dirtyDossiers
    .filter(
      (subquestion, index) =>
        !dossierResults[index] ||
        dossierResults[index].status === "error",
    )
    .map((subquestion) => subquestion.id);
  const spineSubquestions = subquestions.map((subquestion) =>
    dossiersFailed.includes(subquestion.id)
      ? { ...subquestion, dossier: false, page: null }
      : subquestion,
  );

  const synthesis = await retryNull(
    topicSpineSynthPrompt(
      slug,
      desc,
      ok,
      spineSubquestions,
      cards,
    ),
    {
      phase: "Synthesise",
      agentType: "quasi:synthesis-agent",
      label: `${slug}:synthesise-topic`,
      schema: SY_SCHEMA,
    },
    OVERWRITE,
  );
  if (!synthesis || synthesis.status === "error")
    return {
      slug,
      status: "synth_failed",
      items: ok.length,
      notes: synthesis && synthesis.notes,
    };

  const auditPaths = [
    ...new Set([
      `vault/topics/${slug}/00-overview.md`,
      `vault/topics/${slug}/01-resources.md`,
      `vault/topics/${slug}/02-outline.md`,
      ...dirtyDossiers
        .filter(
          (subquestion) =>
            !dossiersFailed.includes(subquestion.id),
        )
        .map(
          (subquestion) =>
            `vault/topics/${slug}/${subquestion.page}`,
        ),
      ...cards
        .filter((card) => card.status === "ok")
        .map((card) => cardPath(slug, card.card_slug)),
    ]),
  ];
  const audit = async (suffix) => {
    const results = await parallel(
      auditPaths.map(
        (path) => () =>
          retryNull(`path: ${path}`, {
            phase: "Audit",
            agentType: "quasi:audit-agent",
            label: `${slug}:audit${suffix}:${path.split("/").pop()}`,
            schema: AU_SCHEMA,
          }),
      ),
    );
    return auditPaths.flatMap((path, index) => {
      const result = results[index];
      if (!result || result.status === "error")
        return [
          {
            path,
            kind: "audit_error",
            reason: "audit agent failed",
            suggested_action: "rerun topic",
          },
        ];
      return (result.escalated || []).map((entry) => ({
        path,
        ...entry,
      }));
    });
  };
  let escalated = await audit("");
  if (escalated.length) {
    const repairPaths = [
      ...new Set(
        escalated.map((entry) => entry.path).filter(Boolean),
      ),
    ];
    await parallel(
      repairPaths.map(
        (path) => () => {
          const reasons = escalated
            .filter((entry) => entry.path === path)
            .map(
              (entry) => `${entry.kind}: ${entry.reason}`,
            )
            .join("; ");
          const reason = `\nreason: audit escalated ${reasons}`;
          if (path.endsWith("/02-outline.md"))
            return guard(
              steerPrompt(
                slug,
                desc,
                round,
                [],
                [...seen],
                0,
                null,
                [],
              ) + reason,
              {
                phase: "Search",
                agentType: "quasi:steer-agent",
                label: `${slug}:repair-outline`,
              },
            );
          const dossier = subquestions.find(
            (subquestion) =>
              subquestion.page &&
              path.endsWith(`/${subquestion.page}`),
          );
          if (dossier)
            return guard(
              topicDossierSynthPrompt(
                slug,
                desc,
                dossier,
                cards,
                [`audit escalated: ${reasons}`],
              ),
              {
                phase: "Synthesise",
                agentType: "quasi:synthesis-agent",
                label: `${slug}:repair-dossier:${dossier.id}`,
              },
            );
          const card = cards.find(
            (candidate) =>
              path === cardPath(slug, candidate.card_slug),
          );
          if (card)
            return guard(
              webcardPrompt(slug, desc, card, steer) + reason,
              {
                phase: "Search",
                agentType: "quasi:webcard-agent",
                label: `${slug}:repair-card:${card.card_slug}`,
              },
            );
          return Promise.resolve({ status: "spine" });
        },
      ),
    );
    await guard(
      topicSpineSynthPrompt(
        slug,
        desc,
        ok,
        spineSubquestions,
        cards,
        escalated.map(
          (entry) =>
            `audit escalated ${entry.kind}: ${entry.reason}`,
        ),
      ),
      {
        phase: "Synthesise",
        agentType: "quasi:synthesis-agent",
        label: `${slug}:repair-topic`,
      },
    );
    escalated = await audit("2");
    if (escalated.length)
      return { slug, status: "audit_escalated", escalated };
  }

  return {
    slug,
    status: "ok",
    items: ok.length,
    cards: cardCount,
    recalled: local.length,
    rounds: round,
    outline: `vault/topics/${slug}/02-outline.md`,
    saturated,
    subquestions: subquestions.map((subquestion) => ({
      id: subquestion.id,
      coverage: subquestion.coverage,
      dossier: !!subquestion.dossier,
    })),
    dossiers_failed: dossiersFailed,
    book_slugs: [
      ...new Set(
        ok
          .filter((item) => item.kind === "book")
          .map((item) => item.slug),
      ),
    ],
    failures: failures.length,
    dead_end:
      (!queue.length && !webTasks.length) || saturated,
  };
}

export async function processTopic(runtime, router, slug, meta) {
  if (
    meta &&
    (meta.maxRounds === 0 ||
      (meta.strict === true && meta.maxRounds === 1)) &&
    (meta.maxCardsPerRound === undefined ||
      meta.maxCardsPerRound === 0)
  )
    return processTopicStrict(runtime, router, slug, meta);
  return processTopicLegacy(runtime, router, slug, meta);
}
