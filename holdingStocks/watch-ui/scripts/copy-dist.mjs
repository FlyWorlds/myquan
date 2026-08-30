import { cpSync, rmSync } from 'node:fs'
import { resolve } from 'node:path'

const root = resolve(import.meta.dirname, '..')
const src = resolve(root, '.output/public')
const dest = resolve(root, 'dist')

rmSync(dest, { recursive: true, force: true })
cpSync(src, dest, { recursive: true })
console.log('copied .output/public -> dist')
