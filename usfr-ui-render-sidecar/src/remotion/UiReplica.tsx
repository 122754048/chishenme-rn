import React from 'react';
import {AbsoluteFill, OffthreadVideo, useCurrentFrame} from 'remotion';

import {directionForText, fontFamilyForText} from '../fonts';

export type UiElement = {
  element_id: string;
  role?: string;
  text: string;
  bbox: [number, number, number, number];
  font_size?: number;
  color?: string;
  background_color?: string;
  text_align?: 'left' | 'center' | 'right';
};

export type UiState = {
  state_id: string;
  frame_ms: number;
  expected_text: string[];
  expected_layout: UiElement[];
};

export type UiReplicaProps = {
  motionVideoUrl: string;
  width: number;
  height: number;
  fps: number;
  durationInFrames: number;
  states: UiState[];
  transitionShell: Record<string, unknown>;
};

const interpolateNumber = (left: number, right: number, progress: number): number =>
  left + (right - left) * progress;

const stateAtFrame = (frame: number, props: UiReplicaProps): UiElement[] => {
  const frameMs = (frame / props.fps) * 1000;
  let before = props.states[0];
  let after = props.states[props.states.length - 1];
  for (const state of props.states) {
    if (state.frame_ms <= frameMs) {
      before = state;
    }
    if (state.frame_ms >= frameMs) {
      after = state;
      break;
    }
  }
  if (before.state_id === after.state_id || after.frame_ms <= before.frame_ms) {
    return before.expected_layout;
  }
  const progress = Math.max(
    0,
    Math.min(1, (frameMs - before.frame_ms) / (after.frame_ms - before.frame_ms)),
  );
  return before.expected_layout.map((element) => {
    const target = after.expected_layout.find((candidate) => candidate.element_id === element.element_id);
    if (!target) {
      return element;
    }
    return {
      ...element,
      text: progress >= 1 ? target.text : element.text,
      bbox: element.bbox.map((value, index) =>
        interpolateNumber(value, target.bbox[index], progress),
      ) as [number, number, number, number],
      font_size: interpolateNumber(
        element.font_size ?? 16,
        target.font_size ?? element.font_size ?? 16,
        progress,
      ),
    };
  });
};

const ExactText: React.FC<{element: UiElement}> = ({element}) => {
  const [x1, y1, x2, y2] = element.bbox;
  const width = Math.max(1, x2 - x1);
  const height = Math.max(1, y2 - y1);
  const fontSize = Math.max(8, Math.min(element.font_size ?? height * 0.48, height * 0.72));
  return (
    <div
      style={{
        position: 'absolute',
        left: x1,
        top: y1,
        width,
        height,
        display: 'flex',
        alignItems: 'center',
        justifyContent:
          element.text_align === 'left'
            ? 'flex-start'
            : element.text_align === 'right'
              ? 'flex-end'
              : 'center',
        boxSizing: 'border-box',
        overflow: 'hidden',
        padding: '0 4px',
        backgroundColor: element.background_color ?? 'transparent',
        color: element.color ?? '#ffffff',
        fontFamily: fontFamilyForText(element.text),
        fontWeight: 600,
        fontSize,
        lineHeight: 1.1,
        letterSpacing: 0,
        textAlign: element.text_align ?? 'center',
        direction: directionForText(element.text),
        whiteSpace: 'pre-wrap',
        overflowWrap: 'anywhere',
      }}
    >
      {element.text}
    </div>
  );
};

export const UiReplica: React.FC<UiReplicaProps> = (props) => {
  const frame = useCurrentFrame();
  const elements = stateAtFrame(frame, props);
  return (
    <AbsoluteFill style={{backgroundColor: '#000000'}}>
      <OffthreadVideo
        src={props.motionVideoUrl}
        muted
        style={{width: props.width, height: props.height, objectFit: 'fill'}}
      />
      {elements.map((element) => (
        <ExactText key={element.element_id} element={element} />
      ))}
    </AbsoluteFill>
  );
};
