import { app } from '../../scripts/app.js'

const NODE_CLASS = 'AtelierXAnimaGenerate'
const INPUT_NAME = 'lora_stack'
const STACK_CONFIG_KEY = 'atelierx_lora_stack'
const LEGACY_WIDGET_START = 13
const LEGACY_WIDGET_COUNT = 6

function normalizeStack(value) {
  if (typeof value !== 'string') return []
  try {
    const parsed = JSON.parse(value)
    if (!Array.isArray(parsed)) return []
    return parsed.flatMap((entry) => {
      if (
        entry &&
        typeof entry === 'object' &&
        typeof entry.name === 'string' &&
        typeof entry.strength === 'number' &&
        Number.isFinite(entry.strength)
      ) {
        return [{ name: entry.name, strength: entry.strength }]
      }
      return []
    })
  } catch {
    return []
  }
}

function serializeStack(entries) {
  return JSON.stringify(entries.map(({ name, strength }) => ({ name, strength })))
}

function migrateLegacyWorkflow(info) {
  const values = info?.widgets_values
  if (!Array.isArray(values) || values.length < LEGACY_WIDGET_START + LEGACY_WIDGET_COUNT) return
  if (typeof values[LEGACY_WIDGET_START] === 'string' && values[LEGACY_WIDGET_START].trim().startsWith('[')) return

  const entries = []
  for (let offset = 0; offset < LEGACY_WIDGET_COUNT; offset += 2) {
    const name = values[LEGACY_WIDGET_START + offset]
    const strength = values[LEGACY_WIDGET_START + offset + 1]
    if (typeof name === 'string' && name !== 'None' && typeof strength === 'number' && Number.isFinite(strength)) {
      entries.push({ name, strength })
    }
  }
  values.splice(LEGACY_WIDGET_START, LEGACY_WIDGET_COUNT, serializeStack(entries))
}

function readLoraOptions(node, inputName) {
  const input = node.constructor.nodeData?.input?.optional?.[inputName]
  const options = input?.[1]?.[STACK_CONFIG_KEY]?.options
  return Array.isArray(options) ? options : []
}

function createStackWidget(node, inputName) {
  let entries = []
  const options = readLoraOptions(node, inputName)
  const container = document.createElement('div')
  container.className = 'atelierx-anima-lora-stack'
  container.style.display = 'grid'
  container.style.gap = '4px'
  container.style.padding = '4px 0'

  // The node input needs a normal, serializable widget.  ComfyUI's DOM
  // widgets use their own value adapter, while workflow persistence tracks
  // the input widget registered for `lora_stack`.  Keep that state widget
  // hidden and make the DOM editor a non-serializable view of it.
  const stateWidget = node.addWidget('text', inputName, '[]', (value) => {
    entries = normalizeStack(value)
    render()
  })
  stateWidget.type = 'hidden'
  stateWidget.options.hidden = true
  stateWidget.computeSize = () => [0, -4]

  const widget = node.addDOMWidget(`${inputName}_editor`, 'ATELIERX_LORA_STACK', container)
  widget.serialize = false
  widget.options.serialize = false
  widget.computeSize = (width) => [width, 32 + Math.max(entries.length, 1) * 34]

  function commit() {
    stateWidget.value = serializeStack(entries)
    node.graph?.setDirtyCanvas(true, true)
  }

  function resize() {
    const size = node.computeSize?.()
    if (size) node.setSize([Math.max(node.size[0], size[0]), Math.max(node.size[1], size[1])])
  }

  function makeButton(label, onClick) {
    const button = document.createElement('button')
    button.type = 'button'
    button.textContent = label
    button.addEventListener('click', onClick)
    return button
  }

  function render() {
    container.replaceChildren()
    for (const [index, entry] of entries.entries()) {
      const row = document.createElement('div')
      row.style.display = 'grid'
      row.style.gridTemplateColumns = 'minmax(0, 1fr) 76px 28px'
      row.style.gap = '4px'

      const select = document.createElement('select')
      for (const name of options) {
        const option = document.createElement('option')
        option.value = name
        option.textContent = name
        option.selected = name === entry.name
        select.append(option)
      }
      if (!options.includes(entry.name)) {
        const unavailable = document.createElement('option')
        unavailable.value = entry.name
        unavailable.textContent = `${entry.name} (unavailable)`
        unavailable.selected = true
        select.prepend(unavailable)
      }
      select.addEventListener('change', () => {
        entries[index].name = select.value
        commit()
      })

      const strength = document.createElement('input')
      strength.type = 'number'
      strength.min = '-100'
      strength.max = '100'
      strength.step = '0.01'
      strength.value = String(entry.strength)
      strength.addEventListener('change', () => {
        const value = Number(strength.value)
        if (Number.isFinite(value)) {
          entries[index].strength = value
          commit()
        }
      })

      row.append(select, strength, makeButton('−', () => {
        entries.splice(index, 1)
        commit()
        render()
      }))
      container.append(row)
    }

    container.append(makeButton('+ Add LoRA', () => {
      if (!options.length) return
      entries.push({ name: options[0], strength: 1.0 })
      commit()
      render()
    }))
    resize()
  }

  const originalOnConfigure = node.onConfigure
  node.onConfigure = function (info) {
    const result = originalOnConfigure?.apply(this, arguments)
    entries = normalizeStack(stateWidget.value)
    render()
    return result
  }
  render()
  return { widget: stateWidget }
}

app.registerExtension({
  name: 'AtelierX.AnimaLoraStack',
  beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData?.name !== NODE_CLASS) return
    const input = nodeData.input?.optional?.[INPUT_NAME]
    if (!input?.[1]?.[STACK_CONFIG_KEY]) return

    const originalOnConfigure = nodeType.prototype.onConfigure
    nodeType.prototype.onConfigure = function (info) {
      migrateLegacyWorkflow(info)
      return originalOnConfigure?.apply(this, arguments)
    }
    nodeData.input.optional[INPUT_NAME] = ['ATELIERX_LORA_STACK', input[1]]
  },
  getCustomWidgets() {
    return {
      ATELIERX_LORA_STACK: createStackWidget
    }
  }
})
