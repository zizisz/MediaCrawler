import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import ts from 'typescript'

const source = readFileSync(new URL('../src/lib/keywords.ts', import.meta.url), 'utf8')
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 } })
const { mergeKeywords } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)

test('multiline phrases preserve spaces and search order', () => {
  const phrases = ['PEEK lens actuator', 'PEEK optical actuator', 'PEEK focus mechanism', 'PEEK zoom mechanism', 'PEEK optical stage', 'PEEK precision gear optics', 'PEEK optical instrument', 'PEEK infrared optics', 'PEEK camera actuator', 'PEEK lens mount', 'PEEK optical positioning', 'PEEK low outgassing optics']
  assert.deepEqual(mergeKeywords('', phrases.join('\r\n')), phrases)
  assert.deepEqual(mergeKeywords(phrases.join(',')), phrases)
  assert.deepEqual(mergeKeywords(phrases[0], '\n' + phrases.join('\n') + '\n'), phrases)
})

test('empty lines, commas, and Chinese phrases', () => {
  assert.deepEqual(mergeKeywords('PEEK lens mount', ' \n\r\nPEEK lens mount， 无油 轴承,PEEK gear'), ['PEEK lens mount', '无油 轴承', 'PEEK gear'])
  assert.deepEqual(mergeKeywords('', '  \r\n '), [])
})
