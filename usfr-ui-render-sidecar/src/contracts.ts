import {z} from 'zod';

const Sha256Schema = z.string().regex(/^[0-9a-f]{64}$/);
const Base64Schema = z.string().min(1).regex(/^[A-Za-z0-9+/]*={0,2}$/);
const ExactTextSchema = z
  .string()
  .min(1)
  .refine(
    (value) => !value.includes('\uFFFD') && !/\?\?/.test(value),
    'text contains replacement or placeholder glyphs',
  );
const PositiveIntegerSchema = z.number().int().positive();
const NonNegativeIntegerSchema = z.number().int().nonnegative();

const TextEncodingSchema = z.object({
  encoding: z.literal('utf-8'),
  replacement_glyphs_forbidden: z.literal(true),
});

const SourceUiInteractionContractSchema = z
  .object({
    schema_version: z.literal('source-ui-interaction/v1'),
    region_id: ExactTextSchema,
    source_window_us: z
      .object({
        start: NonNegativeIntegerSchema,
        end_exclusive: PositiveIntegerSchema,
      })
      .refine((value) => value.end_exclusive > value.start, 'source window is empty'),
    frame_window: z
      .object({
        start: NonNegativeIntegerSchema,
        end_exclusive: PositiveIntegerSchema,
      })
      .refine((value) => value.end_exclusive > value.start, 'frame window is empty'),
    source_fps: z.object({
      num: PositiveIntegerSchema,
      den: PositiveIntegerSchema,
    }),
    display_viewport: z.tuple([PositiveIntegerSchema, PositiveIntegerSchema]),
    ui_roi: z.object({
      x: NonNegativeIntegerSchema,
      y: NonNegativeIntegerSchema,
      width: PositiveIntegerSchema,
      height: PositiveIntegerSchema,
      coordinate_space: z.literal('display_pixels'),
    }),
    language: z.object({
      source: ExactTextSchema,
      target: ExactTextSchema,
      mode: z.enum(['preserve_source', 'localized']),
    }),
    text_encoding: TextEncodingSchema,
    motion: z.object({
      capture_scope: z.literal('ui_roi_only'),
      track_policy: z.literal('source_frame_locked'),
      supported_actions: z.tuple([
        z.literal('drag'),
        z.literal('scroll'),
        z.literal('bounce'),
        z.literal('scale'),
        z.literal('rotate'),
        z.literal('opacity'),
        z.literal('tap'),
      ]),
    }),
    validation: z.object({
      mode: z.literal('basic_anchor_only'),
      automatic_retry: z.literal(false),
      anchor_frames: z.tuple([NonNegativeIntegerSchema, NonNegativeIntegerSchema]),
    }),
  })
  .superRefine((value, context) => {
    const [width, height] = value.display_viewport;
    if (value.ui_roi.x + value.ui_roi.width > width || value.ui_roi.y + value.ui_roi.height > height) {
      context.addIssue({code: 'custom', message: 'UI ROI lies outside the display viewport'});
    }
    const lastFrame = value.frame_window.end_exclusive - 1;
    if (
      value.validation.anchor_frames[0] !== value.frame_window.start ||
      value.validation.anchor_frames[1] !== lastFrame
    ) {
      context.addIssue({code: 'custom', message: 'anchor frames do not bind the frame window'});
    }
    if (value.language.mode === 'preserve_source' && value.language.source !== value.language.target) {
      context.addIssue({code: 'custom', message: 'preserve_source language must not change'});
    }
  });

const LayoutElementSchema = z.object({
  element_id: ExactTextSchema,
  role: ExactTextSchema.optional(),
  text: ExactTextSchema,
  bbox: z.tuple([z.number(), z.number(), z.number(), z.number()]),
  font_size: z.number().positive().optional(),
  color: z.string().min(1).optional(),
  background_color: z.string().min(1).optional(),
  text_align: z.enum(['left', 'center', 'right']).optional(),
});

const UiStateSchema = z.object({
  state_id: ExactTextSchema,
  frame_ms: NonNegativeIntegerSchema,
  expected_text: z.array(ExactTextSchema),
  expected_layout: z.array(LayoutElementSchema),
});

const UiTruthCardSchema = z.object({
  approved_copy: z.array(ExactTextSchema).default([]),
  states: z.array(UiStateSchema).min(1),
});

const UiRenderContractSchema = z.object({
  route: z.string().optional(),
  viewport: z.tuple([PositiveIntegerSchema, PositiveIntegerSchema]),
  state_sequence: z.array(ExactTextSchema).min(1),
  source_ui_interaction_contract: SourceUiInteractionContractSchema,
  source_ui_interaction_contract_sha256: Sha256Schema.optional(),
  language: z
    .object({source: ExactTextSchema, target: ExactTextSchema, mode: z.enum(['preserve_source', 'localized'])})
    .optional(),
  text_encoding: TextEncodingSchema.optional(),
});

const MotionReferenceSchema = z.object({
  sha256: Sha256Schema,
  content_type: z.literal('video/mp4'),
  video_base64: Base64Schema,
  source_ui_interaction_contract: SourceUiInteractionContractSchema,
});

export const RenderRequestSchema = z
  .object({
    schema_version: z.literal('usfr-ui-render-evidence/v1'),
    request_sha256: Sha256Schema,
    source_sha256: Sha256Schema,
    source_content_type: z.string().regex(/^image\//),
    source_base64: Base64Schema,
    ui_truth_card: UiTruthCardSchema,
    ui_render_contract: UiRenderContractSchema,
    motion_reference: MotionReferenceSchema,
    expected_model: z.object({id: ExactTextSchema, sha256: Sha256Schema}),
  })
  .superRefine((value, context) => {
    if (
      JSON.stringify(value.motion_reference.source_ui_interaction_contract) !==
      JSON.stringify(value.ui_render_contract.source_ui_interaction_contract)
    ) {
      context.addIssue({code: 'custom', message: 'motion reference contract does not match render contract'});
    }
    const stateIds = value.ui_truth_card.states.map((state) => state.state_id);
    if (JSON.stringify(stateIds) !== JSON.stringify(value.ui_render_contract.state_sequence)) {
      context.addIssue({code: 'custom', message: 'truth state order does not match render contract'});
    }
  });

export const RenderResponseSchema = z.object({
  schema_version: z.literal('usfr-ui-render-evidence/v1'),
  request_sha256: Sha256Schema,
  source_sha256: Sha256Schema,
  ui_truth_card: UiTruthCardSchema,
  ui_render_contract: UiRenderContractSchema,
  video_base64: Base64Schema,
  video_sha256: Sha256Schema,
  state_sequence: z.array(ExactTextSchema).min(1),
  motion_track_sha256: Sha256Schema,
  model: z.object({id: ExactTextSchema, sha256: Sha256Schema}),
});

export type SourceUiInteractionContract = z.infer<typeof SourceUiInteractionContractSchema>;
export type UiTruthCard = z.infer<typeof UiTruthCardSchema>;
export type UiRenderContract = z.infer<typeof UiRenderContractSchema>;
export type RenderRequest = z.infer<typeof RenderRequestSchema>;
export type RenderResponse = z.infer<typeof RenderResponseSchema>;
