// The browser every test runs in. A surface mounts into a document and reads
// a window, and the sandbox has neither, so happy-dom's are registered on the
// global object before any test file loads — `bunfig.toml` names this file as
// the suite's preload. React is told this is an `act` environment, so a state
// update landing outside one is reported rather than silently deferred.
import { GlobalRegistrator } from "@happy-dom/global-registrator";

GlobalRegistrator.register({ url: "http://localhost/" });
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
