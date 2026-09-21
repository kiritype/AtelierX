#!/usr/bin/env node
'use strict'

const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')

class FakeElement {
  constructor(tagName) {
    this.tagName = tagName
    this.children = []
    this.style = {}
    this.listeners = new Map()
    this.classList = { add() {} }
  }

  append(...children) {
    this.children.push(...children)
  }

  prepend(...children) {
    this.children.unshift(...children)
  }

  replaceChildren(...children) {
    this.children = children
  }

  addEventListener(type, callback) {
    this.listeners.set(type, callback)
  }

  dispatch(type) {
    this.listeners.get(type)?.({ target: this })
  }
}

function collect(element, predicate, found = []) {
  if (predicate(element)) found.push(element)
  for (const child of element.children ?? []) collect(child, predicate, found)
  return found
}

function createNode() {
  const graph = {
    dirtyCalls: 0,
    setDirtyCanvas() {
      this.dirtyCalls += 1
    }
  }
  const node = {
    constructor: {
      nodeData: {
        input: {
          optional: {
            lora_stack: [
              'STRING',
              {
                atelierx_lora_stack: {
                  options: ['first.safetensors', 'second.safetensors']
                }
              }
            ]
          }
        }
      }
    },
    graph,
    size: [320, 200],
    widgets: [],
    addWidget(type, name, value, callback, options = {}) {
      let currentValue = value
      const widget = { type, name, options, computeSize() {} }
      Object.defineProperty(widget, 'value', {
        get: () => currentValue,
        set: (nextValue) => {
          currentValue = nextValue
          callback?.(nextValue)
        }
      })
      this.widgets.push(widget)
      return widget
    },
    addDOMWidget(name, type, element, options = {}) {
      const widget = { name, type, element, options, computeSize() {} }
      this.widgets.push(widget)
      return widget
    },
    computeSize() {
      return this.size
    },
    setSize(size) {
      this.size = size
    }
  }
  return node
}

const sourcePath = path.join(__dirname, '..', 'web', 'atelierx_lora_stack.js')
const source = fs
  .readFileSync(sourcePath, 'utf8')
  .replace("import { app } from '../../scripts/app.js'", 'const app = globalThis.__app')
const app = {
  registerExtension(extension) {
    this.extension = extension
  }
}
const context = { __app: app, console, document: { createElement: (tag) => new FakeElement(tag) } }
context.globalThis = context
vm.runInNewContext(source, context, { filename: sourcePath })

const factory = app.extension.getCustomWidgets().ATELIERX_LORA_STACK
const node = createNode()
const { widget: stateWidget } = factory(node, 'lora_stack')
const editor = node.widgets.find((widget) => widget.name === 'lora_stack_editor')

assert.equal(stateWidget.name, 'lora_stack')
assert.equal(stateWidget.type, 'hidden')
assert.equal(stateWidget.options.hidden, true)
assert.equal(editor.serialize, false)
assert.equal(editor.options.serialize, false)

stateWidget.value = JSON.stringify([
  { name: 'first.safetensors', strength: 0.35 },
  { name: 'second.safetensors', strength: 0.5 }
])
let strengths = collect(editor.element, (element) => element.type === 'number')
assert.equal(strengths.length, 2)
strengths[0].value = '0.4'
strengths[0].dispatch('change')
assert.deepEqual(JSON.parse(stateWidget.value), [
  { name: 'first.safetensors', strength: 0.4 },
  { name: 'second.safetensors', strength: 0.5 }
])

const add = collect(editor.element, (element) => element.textContent === '+ Add LoRA')[0]
add.dispatch('click')
assert.deepEqual(JSON.parse(stateWidget.value), [
  { name: 'first.safetensors', strength: 0.4 },
  { name: 'second.safetensors', strength: 0.5 },
  { name: 'first.safetensors', strength: 1 }
])
assert.ok(node.graph.dirtyCalls >= 2)

process.stdout.write('AtelierX dynamic LoRA frontend widget test passed.\n')
