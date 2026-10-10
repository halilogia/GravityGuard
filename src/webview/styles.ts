// Composes the webview stylesheet from the section files under ./styles.
// Parts 1 and 2 end with a trailing newline so joining with '\n' keeps the original blank line between sections.
import { BASE_STYLES } from './styles/base';
import { STREAM_STYLES } from './styles/stream';
import { INSIGHTS_STYLES } from './styles/insights';

export const WEBVIEW_STYLES: string = [BASE_STYLES, STREAM_STYLES, INSIGHTS_STYLES].join('\n');
