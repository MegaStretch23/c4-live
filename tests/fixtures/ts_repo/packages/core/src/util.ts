import { readFileSync } from 'fs';
import _ from 'lodash';
export const read = (p: string) => readFileSync(p, 'utf8');
