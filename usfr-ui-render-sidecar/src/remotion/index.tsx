import React from 'react';
import {Composition, registerRoot} from 'remotion';

import {UiReplica, type UiReplicaProps} from './UiReplica';

const defaultProps: UiReplicaProps = {
  motionVideoUrl: 'http://127.0.0.1/unused.mp4',
  width: 180,
  height: 320,
  fps: 30,
  durationInFrames: 30,
  states: [
    {
      state_id: 'state-001',
      frame_ms: 0,
      expected_text: [],
      expected_layout: [],
    },
  ],
  transitionShell: {},
};

const Root: React.FC = () => (
  <Composition
    id="UiReplica"
    component={UiReplica}
    durationInFrames={defaultProps.durationInFrames}
    fps={defaultProps.fps}
    width={defaultProps.width}
    height={defaultProps.height}
    defaultProps={defaultProps}
    calculateMetadata={({props}) => ({
      durationInFrames: props.durationInFrames,
      fps: props.fps,
      width: props.width,
      height: props.height,
    })}
  />
);

registerRoot(Root);
