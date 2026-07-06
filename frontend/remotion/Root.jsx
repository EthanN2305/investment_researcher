// Remotion root — registers the StockOfTheDay composition for CLI renders.
// The backend's /learn/render endpoint invokes:
//   npx remotion render remotion/index.jsx StockOfTheDay out.mp4 --props=...
// The composition length follows the `duration_sec` prop (30 or 65).
import React from "react";
import { Composition } from "remotion";
import StockVideo, {
  DURATION_IN_FRAMES,
  FPS,
  videoDurationInFrames,
} from "../src/video/StockVideo.jsx";

export function RemotionRoot() {
  return (
    <Composition
      id="StockOfTheDay"
      component={StockVideo}
      durationInFrames={DURATION_IN_FRAMES}
      fps={FPS}
      width={1080}
      height={1920}
      calculateMetadata={({ props }) => ({
        props,
        durationInFrames: videoDurationInFrames(props.duration_sec ?? 30),
      })}
    />
  );
}
