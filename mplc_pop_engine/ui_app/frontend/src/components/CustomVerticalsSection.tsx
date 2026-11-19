import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  addCustomVerticalChannel,
  createCustomVertical,
  deleteCustomVertical,
  deleteCustomVerticalChannel,
  fetchCustomVerticals,
  updateCustomVerticalChannel,
  type CustomVerticalChannelRow,
  type CustomVerticalChannelType,
  type CustomVerticalRow,
} from "../api/client";

/** Custom Vertical Builder -- folded into the Settings tab per Jeff's
 * 2026-11-18 choice ("Fold into Settings"), not a new top-level tab. See
 * claude/Custom_Vertical_Builder_Design.md in the MPLC project for the
 * full design: a vertical's "recipe" is an ORDERED list of channels, the
 * enrichment loop stops at the first one that returns PROSPECT (shown
 * here as plain step numbers + up/down reordering, not drag-and-drop --
 * simplest thing that expresses "order matters, first PROSPECT wins").
 *
 * The one-time LLM config-generation call happens server-side when a
 * channel is added or regenerated (production/channels/
 * config_from_description.py) -- this component only shows Jeff the
 * description box and, once generated, the resulting query
 * templates/target/excluded spaces as hand-editable JSON, per the design
 * doc's "Jeff can see and hand-edit the generated config afterward rather
 * than only trusting the LLM's first pass." */

const CHANNEL_TYPE_LABELS: Record<CustomVerticalChannelType, string> = {
  serper_image: "Serper image search + VLM",
  youtube_video: "YouTube video + YOLO + VLM",
  website_scrape: "Website scrape + VLM",
};

const CHANNEL_TYPE_HINTS: Record<CustomVerticalChannelType, string> = {
  serper_image: "Finds photos via Google Images. Good default for most verticals.",
  youtube_video: "Finds tour/walkthrough videos via YouTube. Costs more per account (video download + frame extraction).",
  website_scrape: "Scrapes the account's own website (gallery/amenity pages). Free, but only works if the site actually has photos.",
};

function ChannelRow({
  verticalKey,
  channel,
  prevChannel,
  nextChannel,
}: {
  verticalKey: string;
  channel: CustomVerticalChannelRow;
  prevChannel: CustomVerticalChannelRow | null;
  nextChannel: CustomVerticalChannelRow | null;
}) {
  const queryClient = useQueryClient();
  const [editingConfig, setEditingConfig] = useState(false);
  const [configDraft, setConfigDraft] = useState(channel.config_json ?? "");
  const [regenDescription, setRegenDescription] = useState(channel.description);
  const [showRegen, setShowRegen] = useState(false);

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["custom-verticals"] });

  const update = useMutation({
    mutationFn: (input: Parameters<typeof updateCustomVerticalChannel>[2]) =>
      updateCustomVerticalChannel(verticalKey, channel.id, input),
    onSuccess: invalidate,
  });

  const remove = useMutation({
    mutationFn: () => deleteCustomVerticalChannel(verticalKey, channel.id),
    onSuccess: invalidate,
  });

  // Was a bare Promise.all(...).then(invalidate) with no .catch -- every
  // OTHER mutation in this file surfaces .isError, but a failed reorder
  // (e.g. a network blip on one of the two requests) used to silently
  // half-apply with zero feedback, leaving the two rows with duplicate or
  // inconsistent step_order and no way to tell something went wrong.
  // Wrapped as a real useMutation (2026-11-18) so it reports errors the
  // same way update/remove already do.
  const reorder = useMutation({
    mutationFn: (other: CustomVerticalChannelRow) =>
      // Simple adjacent swap -- reordering a short list, not a general
      // drag-and-drop, so two updates (this row <-> its neighbor) is
      // enough. Both fire before the shared query invalidation so the
      // list re-fetches once, with both new positions already
      // committed, rather than flickering through an inconsistent
      // intermediate order.
      Promise.all([
        updateCustomVerticalChannel(verticalKey, channel.id, { step_order: other.step_order }),
        updateCustomVerticalChannel(verticalKey, other.id, { step_order: channel.step_order }),
      ]),
    onSuccess: invalidate,
  });

  let parsedConfig: { query_templates?: string[]; target_spaces?: string[]; excluded_spaces?: string[] } | null = null;
  try {
    parsedConfig = channel.config_json ? JSON.parse(channel.config_json) : null;
  } catch {
    parsedConfig = null;
  }

  return (
    <div className={`custom-channel-row${channel.enabled ? "" : " custom-channel-disabled"}`}>
      <div className="custom-channel-header">
        <span className="custom-channel-step">Step {channel.step_order + 1}</span>
        <span className="custom-channel-type">{CHANNEL_TYPE_LABELS[channel.channel_type]}</span>
        <label className="custom-channel-toggle">
          <input
            type="checkbox"
            checked={channel.enabled}
            onChange={(e) => update.mutate({ enabled: e.target.checked })}
          />
          Enabled
        </label>
        <div className="custom-channel-order-buttons">
          <button
            type="button"
            disabled={!prevChannel || reorder.isPending}
            title="Move earlier"
            onClick={() => prevChannel && reorder.mutate(prevChannel)}
          >
            ↑
          </button>
          <button
            type="button"
            disabled={!nextChannel || reorder.isPending}
            title="Move later"
            onClick={() => nextChannel && reorder.mutate(nextChannel)}
          >
            ↓
          </button>
        </div>
        <button
          type="button"
          className="custom-channel-delete"
          onClick={() => {
            // Was a single click with no confirm -- unlike "Delete
            // vertical" below, which does confirm despite being harder to
            // reach (one header button vs. this one sitting inline among
            // small ↑/↓ icon buttons, a much easier misclick target). A
            // misclick here permanently destroys the channel and the
            // config it cost a real LLM call to generate, with no undo.
            if (
              window.confirm(
                `Remove step ${channel.step_order + 1} (${CHANNEL_TYPE_LABELS[channel.channel_type]})? ` +
                  "This deletes its generated config and can't be undone.",
              )
            ) {
              remove.mutate();
            }
          }}
        >
          Remove
        </button>
      </div>

      <p className="custom-channel-description">"{channel.description}"</p>

      {parsedConfig ? (
        <div className="custom-channel-config">
          <div>
            <strong>Target spaces:</strong> {(parsedConfig.target_spaces ?? []).join(", ") || "—"}
          </div>
          <div>
            <strong>Excluded spaces:</strong> {(parsedConfig.excluded_spaces ?? []).join(", ") || "—"}
          </div>
          {channel.channel_type !== "website_scrape" && (
            <div>
              <strong>Query templates:</strong>
              <ul>
                {(parsedConfig.query_templates ?? []).map((q, i) => (
                  <li key={i}>
                    <code>{q}</code>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <div className="custom-channel-cost-note">
            Config generated once for ${channel.config_generated_cost.toFixed(4)} — not charged again per account.
          </div>
        </div>
      ) : (
        <p className="action-error">No generated config — this step will fail at run time until regenerated.</p>
      )}

      <div className="custom-channel-actions">
        {!editingConfig && (
          <button type="button" onClick={() => { setConfigDraft(channel.config_json ?? ""); setEditingConfig(true); }}>
            Hand-edit config
          </button>
        )}
        <button type="button" onClick={() => setShowRegen((v) => !v)}>
          Regenerate from description
        </button>
      </div>

      {editingConfig && (
        <div className="custom-channel-config-editor">
          <textarea
            rows={5}
            value={configDraft}
            onChange={(e) => setConfigDraft(e.target.value)}
            placeholder='{"query_templates": [...], "target_spaces": [...], "excluded_spaces": [...]}'
          />
          <div className="custom-channel-actions">
            <button
              type="button"
              className="primary"
              disabled={update.isPending}
              onClick={() => update.mutate({ config_json: configDraft }, { onSuccess: () => setEditingConfig(false) })}
            >
              Save config
            </button>
            <button type="button" onClick={() => setEditingConfig(false)}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {showRegen && (
        <div className="custom-channel-config-editor">
          <textarea
            rows={3}
            value={regenDescription}
            onChange={(e) => setRegenDescription(e.target.value)}
            placeholder="Describe what this channel should look for, in plain English…"
          />
          <div className="custom-channel-actions">
            <button
              type="button"
              className="primary"
              disabled={update.isPending || !regenDescription.trim()}
              onClick={() => {
                // Was a single click with no confirm, unlike "Delete
                // vertical" below -- but this one actually spends real
                // money (a real LLM call), and sits right next to
                // "Hand-edit config" above, which has no side effect at
                // all. A misclick between the two used to burn a paid
                // regeneration with no undo.
                if (
                  !window.confirm(
                    "Regenerate this step's config from the description above? " +
                      "This makes a real (small, one-time) LLM call and replaces the current config.",
                  )
                ) {
                  return;
                }
                update.mutate(
                  { regenerate_from_description: regenDescription },
                  { onSuccess: () => setShowRegen(false) },
                );
              }}
            >
              {update.isPending ? "Regenerating…" : "Regenerate (one-time LLM call)"}
            </button>
            <button type="button" onClick={() => setShowRegen(false)}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {(update.isError || remove.isError || reorder.isError) && (
        <p className="action-error">
          {String(((update.error ?? remove.error ?? reorder.error) as Error)?.message ?? "Request failed")}
        </p>
      )}
    </div>
  );
}

function AddChannelForm({ verticalKey }: { verticalKey: string }) {
  const queryClient = useQueryClient();
  const [channelType, setChannelType] = useState<CustomVerticalChannelType>("serper_image");
  const [description, setDescription] = useState("");

  const add = useMutation({
    mutationFn: () => addCustomVerticalChannel(verticalKey, channelType, description),
    onSuccess: () => {
      setDescription("");
      queryClient.invalidateQueries({ queryKey: ["custom-verticals"] });
    },
  });

  return (
    <div className="custom-add-channel">
      <select value={channelType} onChange={(e) => setChannelType(e.target.value as CustomVerticalChannelType)}>
        {(Object.keys(CHANNEL_TYPE_LABELS) as CustomVerticalChannelType[]).map((t) => (
          <option key={t} value={t}>
            {CHANNEL_TYPE_LABELS[t]}
          </option>
        ))}
      </select>
      <p className="custom-channel-hint">{CHANNEL_TYPE_HINTS[channelType]}</p>
      <textarea
        rows={2}
        placeholder="Describe what this channel should look for (e.g. 'photos of the gym or break room at corporate HQ')…"
        value={description}
        onChange={(e) => setDescription(e.target.value)}
      />
      <button
        type="button"
        className="primary"
        disabled={add.isPending || !description.trim()}
        onClick={() => add.mutate()}
      >
        {add.isPending ? "Generating config (one-time LLM call)…" : "Add step"}
      </button>
      {add.isError && <p className="action-error">{String((add.error as Error)?.message ?? add.error)}</p>}
    </div>
  );
}

function VerticalCard({ vertical }: { vertical: CustomVerticalRow }) {
  const queryClient = useQueryClient();
  const [expanded, setExpanded] = useState(true);

  const remove = useMutation({
    mutationFn: () => deleteCustomVertical(vertical.vertical_key),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["custom-verticals"] }),
  });

  const sortedChannels = [...vertical.channels].sort((a, b) => a.step_order - b.step_order);
  const totalConfigCost = sortedChannels.reduce((sum, c) => sum + c.config_generated_cost, 0);

  return (
    <div className="custom-vertical-card">
      <div className="custom-vertical-header" onClick={() => setExpanded((v) => !v)}>
        <span className="custom-vertical-title">
          {expanded ? "▾" : "▸"} {vertical.display_name}
        </span>
        <span className="custom-vertical-key">({vertical.vertical_key})</span>
        <span className="custom-vertical-step-count">
          {sortedChannels.length} step{sortedChannels.length === 1 ? "" : "s"}
        </span>
        {totalConfigCost > 0 && (
          <span className="custom-channel-cost-note">${totalConfigCost.toFixed(4)} spent generating config</span>
        )}
        <button
          type="button"
          className="custom-vertical-delete"
          onClick={(e) => {
            e.stopPropagation();
            if (window.confirm(`Delete "${vertical.display_name}" and all its steps? This can't be undone.`)) {
              remove.mutate();
            }
          }}
        >
          Delete vertical
        </button>
      </div>

      {expanded && (
        <div className="custom-vertical-body">
          <p className="step-description">
            Runs in order below. The run stops at the first enabled step that finds a PROSPECT — later steps
            don't run (and aren't charged) once one hits.
          </p>
          {sortedChannels.map((c, i) => (
            <ChannelRow
              key={c.id}
              verticalKey={vertical.vertical_key}
              channel={c}
              prevChannel={i > 0 ? sortedChannels[i - 1] : null}
              nextChannel={i < sortedChannels.length - 1 ? sortedChannels[i + 1] : null}
            />
          ))}
          <AddChannelForm verticalKey={vertical.vertical_key} />
        </div>
      )}
    </div>
  );
}

function NewVerticalForm() {
  const queryClient = useQueryClient();
  const [displayName, setDisplayName] = useState("");
  const [verticalKey, setVerticalKey] = useState("");
  const [keyEdited, setKeyEdited] = useState(false);

  const create = useMutation({
    mutationFn: () => createCustomVertical(verticalKey, displayName),
    onSuccess: () => {
      setDisplayName("");
      setVerticalKey("");
      setKeyEdited(false);
      queryClient.invalidateQueries({ queryKey: ["custom-verticals"] });
    },
  });

  const slugify = (s: string) => s.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");

  return (
    <div className="custom-new-vertical">
      <h4>New vertical</h4>
      <div className="custom-new-vertical-fields">
        <input
          type="text"
          placeholder="Display name (e.g. Assisted Living Dayrooms)"
          value={displayName}
          onChange={(e) => {
            setDisplayName(e.target.value);
            if (!keyEdited) setVerticalKey(slugify(e.target.value));
          }}
        />
        <input
          type="text"
          placeholder="key_slug"
          value={verticalKey}
          onChange={(e) => {
            setKeyEdited(true);
            setVerticalKey(slugify(e.target.value));
          }}
        />
        <button
          type="button"
          className="primary"
          disabled={create.isPending || !displayName.trim() || !verticalKey.trim()}
          onClick={() => create.mutate()}
        >
          {create.isPending ? "Creating…" : "Create vertical"}
        </button>
      </div>
      {create.isError && <p className="action-error">{String((create.error as Error)?.message ?? create.error)}</p>}
    </div>
  );
}

export function CustomVerticalsSection() {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["custom-verticals"],
    queryFn: fetchCustomVerticals,
  });

  return (
    <div className="custom-verticals-section">
      <h3>Custom Verticals</h3>
      <p className="step-description">
        Define a new vertical without writing code: pick which evidence channels to use (Serper image search,
        YouTube video, website scrape), describe what each should look for in plain English, and set the order
        they run in. The first enabled channel that finds a PROSPECT wins — later ones are skipped.
      </p>

      {isLoading && <p>Loading…</p>}
      {isError && <p className="action-error">Failed to load custom verticals: {String(error)}</p>}

      {data && data.length === 0 && <p className="upload-missing">No custom verticals yet — add one below.</p>}
      {data && data.map((v) => <VerticalCard key={v.vertical_key} vertical={v} />)}

      <NewVerticalForm />
    </div>
  );
}
