export function shouldSubmitComposer(event, options) {
  const { enterToSend, isComposing } = options;
  if (!enterToSend) {
    return false;
  }
  if (event.key !== "Enter") {
    return false;
  }
  if (event.shiftKey || event.nativeEvent?.shiftKey) {
    return false;
  }
  if (isComposing || event.nativeEvent?.isComposing) {
    return false;
  }
  return true;
}
